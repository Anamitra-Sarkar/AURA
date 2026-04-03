from setuptools import setup, find_packages

setup(
    name="aura-client",
    version="1.0.0",
    packages=find_packages(),
    install_requires=[],
    entry_points={"console_scripts": ["aura-client=aura_client.main:main"]},
)
