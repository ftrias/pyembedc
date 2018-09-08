import setuptools

with open("README.md", "r") as fh:
    long_description = fh.read()
    
setuptools.setup(
    name="pyembedc",
    version="1.25",
    author="Fernando Trias",
    author_email="sub@trias.org",
    description="Embedded C/C++ in Python Source",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="http://github.com/ftrias/pyembedc",
    packages=["pyembedc"],
    classifiers=[
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
)
