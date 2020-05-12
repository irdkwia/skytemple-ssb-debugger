#  Copyright 2020 Parakoopa
#
#  This file is part of SkyTemple.
#
#  SkyTemple is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  SkyTemple is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with SkyTemple.  If not, see <https://www.gnu.org/licenses/>.
import json
import os
import threading
from functools import partial
from typing import Callable, Optional, Dict, Tuple, TYPE_CHECKING

from gi.repository import GLib

from explorerscript.source_map import MacroSourceMapping
from skytemple_files.common.project_file_manager import EXPLORERSCRIPT_INCLUSION_MAP_SUFFIX
from skytemple_ssb_debugger.model.breakpoint_manager import BreakpointManager
from skytemple_ssb_debugger.model.script_file_context.abstract import AbstractScriptFileContext
from skytemple_ssb_debugger.model.ssb_files.file import SsbLoadedFile
from skytemple_ssb_debugger.model.ssb_files.file_manager import SsbFileManager

if TYPE_CHECKING:
    from skytemple_ssb_debugger.controller.editor_notebook import EditorNotebookController


class ExpsMacroFileScriptFileContext(AbstractScriptFileContext):
    """A file context for an exps macro file. Keeps track of all macros that use the file."""
    def __init__(self, absolute_path: str, ssb_fm: SsbFileManager,
                 breakpoint_manager: BreakpointManager, editor_notebook_controller: 'EditorNotebookController'):
        super().__init__()
        self._ssb_fm = ssb_fm
        self._absolute_path = absolute_path
        self._relative_path = absolute_path.replace(self._ssb_fm.project_fm.dir() + os.path.sep, "")
        assert self._absolute_path != self._relative_path
        self._breakpoint_manager = breakpoint_manager
        self._editor_notebook_controller = editor_notebook_controller
        # A map of all managed ssb states (breakable, ram_state_up_to_date)
        self._ssbs_states: Dict[str, Tuple[bool, bool]] = {}
        self._we_triggered_the_reload = False

    @property
    def ssb_filepath(self) -> Optional[str]:
        return None

    @property
    def exps_filepath(self) -> str:
        return self._absolute_path

    @property
    def breakpoint_manager(self) -> BreakpointManager:
        return self._breakpoint_manager

    def on_ssb_reload(self, loaded_ssb: SsbLoadedFile):
        if self._on_ssbs_state_change:
            self._on_ssbs_reload(loaded_ssb.filename)

    def on_ssb_property_change(self, loaded_ssb: SsbLoadedFile, name, value):
        self._ssbs_states[loaded_ssb.filename] = (not loaded_ssb.not_breakable, loaded_ssb.ram_state_up_to_date)

    def request_ssbs_state(self):
        self._inform_ssbs_state_change()
        for ssb_file in self._registered_ssbs:
            self._on_ssbs_reload(ssb_file.filename)

    def _inform_ssbs_state_change(self):
        if len(self._ssbs_states) < 1:
            return
        breakables, ram_states = zip(*self._ssbs_states.values())
        self._on_ssbs_state_change(all(breakables), all(ram_states))

    def load(
        self,
        load_exps: bool,
        load_view_callback: Callable[[str, bool, str], None],
        after_callback: Callable[[], None],
        exps_exception_callback: Callable[[BaseException], None],
        exps_hash_changed_callback: Callable[[Callable, Callable], None],
        ssbs_not_available_callback: Callable[[], None]
    ):
        ssbs_not_available_callback()
        if not load_exps:
            return  # SsbScript not supported.

        def load_thread():
            try:
                # 1. Load the epxs file
                exps_source, _ = self._ssb_fm.project_fm.explorerscript_load(self._relative_path, sourcemap=False)

                # 2. Load a list of all ssbs file from the inclusion map,
                #    request them from the file manager and watch them
                inclusion_map_path = self._absolute_path + EXPLORERSCRIPT_INCLUSION_MAP_SUFFIX
                inclusion_map = []
                if os.path.exists(inclusion_map_path):
                    with open(inclusion_map_path, 'r') as f:
                        inclusion_map = json.load(f)
                for ssb_filename in inclusion_map:
                    try:
                        self._register_ssb_handler(
                            self._ssb_fm.get(ssb_filename)
                        )
                    except FileNotFoundError:
                        # Ignore deleted ssbs
                        pass
            except Exception as ex:
                GLib.idle_add(partial(exps_exception_callback, ex))
            else:
                GLib.idle_add(partial(
                    load_view_callback, exps_source, True, 'exps'
                ))

            GLib.idle_add(partial(self._after_load, after_callback))

        threading.Thread(target=load_thread).start()

    def _after_load(self, after_callback: Callable[[], None]):
        # 3. Compare the hashes of the ssb files and check the state,
        #    of the loaded ssb files. If hashes match and is breakable
        #    add opcode markers to the buffer
        if self._do_insert_opcode_text_mark:
            for loaded_ssb in self._registered_ssbs:
                if self._is_breakable(loaded_ssb):
                    for opcode_offset, source_mapping in loaded_ssb.exps.source_map:
                        if isinstance(source_mapping, MacroSourceMapping) and self._sm_entry_is_for_us(
                                loaded_ssb, source_mapping.relpath_included_file
                        ):
                            self._do_insert_opcode_text_mark(
                                True, loaded_ssb.filename, opcode_offset,
                                source_mapping.line, source_mapping.column, False, False
                            )
                        # Also insert opcode text marks for macro calls
                        if isinstance(source_mapping, MacroSourceMapping) and source_mapping.called_in and source_mapping.called_in:
                            cin_fn, cin_line, cin_col = source_mapping.called_in
                            if self._sm_entry_is_for_us(loaded_ssb, cin_fn):
                                self._do_insert_opcode_text_mark(
                                    True, loaded_ssb.filename, opcode_offset,
                                    cin_line, cin_col, False, True
                                )
        after_callback()

    def save(self, save_text: str, save_exps: bool, error_callback: Callable[[BaseException], None],
             success_callback: Callable[[], None]):
        if not save_exps:
            return  # not supported.

        def save_thread():
            try:
                ready_to_reload_list, included_exps_files_list = self._ssb_fm.save_explorerscript_macro(
                    self._absolute_path, save_text, self._registered_ssbs
                )
            except Exception as err:
                GLib.idle_add(partial(error_callback, err))
                return
            else:
                GLib.idle_add(partial(self._after_save, ready_to_reload_list, included_exps_files_list, success_callback))

        threading.Thread(target=save_thread).start()

    def _after_save(self, ready_to_reload_list, included_exps_files_list, success_callback: Callable[[], None]):
        zipped = zip(self._registered_ssbs, ready_to_reload_list, included_exps_files_list)
        self._we_triggered_the_reload = True
        for loaded_ssb, ready_to_reload, included_exps_files in zipped:
            for exps_abs_path in included_exps_files:
                self._editor_notebook_controller.on_exps_macro_ssb_changed(exps_abs_path, loaded_ssb.filename)
            self._editor_notebook_controller.on_ssb_changed_externally(loaded_ssb.filename, ready_to_reload)
        # Temporary text marks were not built by the callback in on_ssb_changed_externally
        self._we_triggered_the_reload = False

        success_callback()

        for loaded_ssb, ready_to_reload, included_exps_files in zipped:
            if ready_to_reload:
                self._ssb_fm.force_reload(loaded_ssb.filename)

    def on_ssb_changed_externally(self, ssb_filename, ready_to_reload):
        loaded_ssb = None
        for candidate in self._registered_ssbs:
            if candidate.filename == ssb_filename:
                loaded_ssb = candidate
                break
        if loaded_ssb is not None:
            # Build temporary text marks for the new source map. We will replace
            # the real ones with those in on_ssb_reloaded
            if self._do_insert_opcode_text_mark:
                for opcode_offset, source_mapping in loaded_ssb.exps.source_map:
                    if isinstance(source_mapping, MacroSourceMapping) and self._sm_entry_is_for_us(
                            loaded_ssb, source_mapping.relpath_included_file
                    ):
                        self._do_insert_opcode_text_mark(
                            True, ssb_filename, opcode_offset,
                            source_mapping.line, source_mapping.column, True, False
                        )
                    # Also insert opcode text marks for macro calls
                    if isinstance(source_mapping, MacroSourceMapping) and source_mapping.called_in and source_mapping.called_in:
                        cin_fn, cin_line, cin_col = source_mapping.called_in
                        if self._sm_entry_is_for_us(loaded_ssb, cin_fn):
                            self._do_insert_opcode_text_mark(
                                True, loaded_ssb.filename, opcode_offset,
                                cin_line, cin_col, True, True
                            )
            if ready_to_reload and not self._we_triggered_the_reload:
                self._ssb_fm.force_reload(ssb_filename)

    def on_exps_macro_ssb_changed(self, exps_abs_path, ssb_filename):
        # If we don't watch a ssb file yet, we will now.
        if exps_abs_path == self._absolute_path:
            if ssb_filename not in [ssb.filename for ssb in self._registered_ssbs]:
                self._register_ssb_handler(
                    self._ssb_fm.get(ssb_filename)
                )
            if not self._we_triggered_the_reload:
                self.on_ssb_changed_externally(ssb_filename, True)
            # Otherwise opcode text marks get added by on_ssb_changed_externally.

    def _is_breakable(self, loaded_ssb: SsbLoadedFile):
        return not loaded_ssb.not_breakable and self._ssb_fm.project_fm.explorerscript_hash_up_to_date(
            loaded_ssb.filename, loaded_ssb.exps.ssb_hash
        )

    def _sm_entry_is_for_us(self, loaded_ssb: SsbLoadedFile, cmp_path: str):
        relpath_of_us_to_ssb_source = os.path.relpath(self._absolute_path, os.path.dirname(loaded_ssb.exps.full_path))
        return cmp_path == relpath_of_us_to_ssb_source