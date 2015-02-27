import codecs
from setuptools import setup, find_packages

VERSION = '0.0.0'

entry_points = {
	'console_scripts': [
	],
	"z3c.autoinclude.plugin": [
		'target = nti.app',
	],
}

import platform
py_impl = getattr(platform, 'python_implementation', lambda: None)
IS_PYPY = py_impl() == 'PyPy'

setup(
	name='nti.app.store',
	version=VERSION,
	author='Jason Madden',
	author_email='jason@nextthought.com',
	description="NTI Store Integration",
	long_description=codecs.open('README.rst', encoding='utf-8').read(),
	license='Proprietary',
	keywords='pyramid preference',
	classifiers=[
		'Intended Audience :: Developers',
		'Natural Language :: English',
		'Operating System :: OS Independent',
		'Programming Language :: Python :: 2',
		'Programming Language :: Python :: 2.7',
		'Programming Language :: Python :: Implementation :: CPython'
	],
	packages=find_packages('src'),
	package_dir={'': 'src'},
	namespace_packages=['nti', 'nti.app'],
	install_requires=[
		'setuptools',
		'nti.store'
	],
	entry_points=entry_points
)
