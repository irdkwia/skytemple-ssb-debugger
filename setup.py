from setuptools import setup, find_packages

# README read-in
from os import path
this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, 'README.rst'), encoding='utf-8') as f:
    long_description = f.read()
# END README read-in

setup(
    name='skytemple-ssb-debugger',
    version='0.0.2a1',
    packages=find_packages(),
    description='Script Engine Debugger for Pokémon Mystery Dungeon Explorers of Sky (EU/US)',
    long_description=long_description,
    long_description_content_type='text/x-rst',
    url='https://github.com/SkyTemple/skytemple-ssb-debugger',
    install_requires=[
        'ndspy >= 3.0.0',
        'skytemple-files >= 0.0.2a1',
        'pygobject >= 3.26.0',
        'pycairo >= 1.16.0',
        'py-desmume >= 0.0.1',
        'explorerscript >= 0.0.2a1',
        'nest-asyncio == 1.2.3; python_version<"3.7"',
        'nest-asyncio >= 1.3.0; python_version>="3.7"'
    ],
    classifiers=[
        'Development Status :: 2 - Pre-Alpha',
        'Programming Language :: Python',
        'License :: OSI Approved :: GNU General Public License v3 or later (GPLv3+)',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8'
    ],
    package_data={'skytemple_ssb_debugger': ['*.lang', '*.css', '*.glade', '**/*.glade', 'data/*/*/*/*/*']},
    entry_points='''
        [console_scripts]
        skytemple-ssb-debugger=skytemple_ssb_debugger.main:main
    ''',
)
