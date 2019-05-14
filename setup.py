import codecs
from setuptools import setup, find_packages

entry_points = {
    'console_scripts': [
    ],
    "z3c.autoinclude.plugin": [
        'target = nti.app',
    ],
}

TESTS_REQUIRE = [
    'nti.app.testing',
    'nti.testing',
    'zope.dottedname',
    'zope.testrunner',
]


def _read(fname):
    with codecs.open(fname, encoding='utf-8') as f:
        return f.read()


setup(
    name='nti.app.store',
    version=_read('version.txt').strip(),
    author='Jason Madden',
    author_email='jason@nextthought.com',
    description="NTI Store Integration",
    long_description=(_read('README.rst') + '\n\n' + _read('CHANGES.rst')),
    license='Apache',
    keywords='pyramid store',
    classifiers=[
        'Framework :: Zope',
        'Framework :: Pyramid',
        'Intended Audience :: Developers',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 2',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: Implementation :: CPython',
        'Programming Language :: Python :: Implementation :: PyPy',
    ],
    url="https://github.com/NextThought/nti.app.store",
    zip_safe=True,
    packages=find_packages('src'),
    package_dir={'': 'src'},
    include_package_data=True,
    namespace_packages=['nti', 'nti.app'],
    tests_require=TESTS_REQUIRE,
    install_requires=[
        'setuptools',
        'gevent',
        'isodate',
	'nti.app.invitations',
        'nti.base',
        'nti.common',
        'nti.coremetadata',
        'nti.externalization',
        'nti.links',
        'nti.namedfile',
        'nti.metadata',
        'nti.ntiids',
        'nti.property',
        'nti.site',
        'nti.store',
        'nti.traversal',
        'nti.zodb',
        'pyramid',
        'requests',
        'simplejson',
        'six',
        'transaction',
        'zope.annotation',
        'zope.cachedescriptors',
        'zope.component',
        'zope.container',
        'zope.event',
        'zope.file',
        'zope.i18nmessageid',
        'zope.interface',
        'zope.intid',
        'zope.lifecycleevent',
        'zope.location',
        'zope.proxy',
        'zope.security',
        'zope.traversing',
    ],
    extras_require={
        'test': TESTS_REQUIRE,
        'docs': [
            'Sphinx',
            'repoze.sphinx.autointerface',
            'sphinx_rtd_theme',
        ],
    },
    entry_points=entry_points,
)
