try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup
    
setup(name='embedc',
    version='1.20',
    py_modules=['pyembedc'],
    description='Embedded C/C++ in Python Source',
    author='Fernando Trias',
    author_email='sub@trias.org',
    url='http://github.com/ftrias/pyembedc'
    )
