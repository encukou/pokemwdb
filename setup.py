from setuptools import setup, find_packages

setup(
    name='pokemwdb',
    version='0.1',
    author='En-Cu-Kou',
    author_email='encukou@gmail.com',
    install_requires=[
        'pyyaml',
        'pokedex',
        'SQLAlchemy>=0.7',
        'diff-match-patch',
        'termcolor',
    ],
    packages=find_packages(exclude=['ez_setup']),
)
