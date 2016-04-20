import logging
import re
try:
    import dnf
except ImportError:
    dnf = None #TODO forbid to import/use DantifiedNameConvertor

from pyp2rpm import settings


logger = logging.getLogger(__name__)


class NameConvertor(object):

    def __init__(self, distro):
        self.distro = distro
        self.reg_start = re.compile(r'^python(\d*|)-(.*)')
        self.reg_end = re.compile(r'(.*)-(python)(\d*|)$')

    @staticmethod
    def rpm_versioned_name(name, version, default_number=False):
        """Properly versions the name.
        For example:
        rpm_versioned_name('python-foo', '26') will return python26-foo
        rpm_versioned_name('pyfoo, '3') will return python3-pyfoo

        If version is same as settings.DEFAULT_PYTHON_VERSION, no change is done.

        Args:
            name: name to version
            version: version or None
        Returns:
            Versioned name or the original name if given version is None.
        """
        regexp = re.compile(r'^python(\d*|)-(.*)')

        if not version or version == settings.DEFAULT_PYTHON_VERSION and not default_number:
            found = regexp.search(name)
            # second check is to avoid renaming of python2-devel to python-devel
            if found and found.group(2) != 'devel':
                return 'python-{0}'.format(regexp.search(name).group(2))
            return name

        versioned_name = name
        if version:

            if regexp.search(name):
                versioned_name = re.sub(r'^python(\d*|)-', 'python{0}-'.format(version), name)
            else:
                versioned_name = 'python{0}-{1}'.format(version, name)

        return versioned_name

    def rpm_name(self, name, python_version=None):
        """Returns name of the package coverted to (possibly) correct package 
           name according to Packaging Guidelines.
        Args:
            name: name to convert
            python_version: python version for which to retrieve the name of the package
        Returns:
            Converted name of the package, that should be in line with Fedora Packaging Guidelines.
            If for_python is not None, the returned name is in form python%(version)s-%(name)s
        """
        logger.debug('Converting name: {0} to rpm name.'.format(name))
        rpmized_name = self.base_name(name)

        rpmized_name = 'python-{0}'.format(rpmized_name)

        if self.distro == 'mageia':
            rpmized_name = rpmized_name.lower()
        logger.debug('Rpmized name of {0}: {1}.'.format(name, rpmized_name))
        return NameConvertor.rpm_versioned_name(rpmized_name, python_version)

    def base_name(self, name):
        """Removes any python prefixes of suffixes from name if present."""
        base_name = name.replace('.', "-")
        # remove python prefix if present
        found_prefix = self.reg_start.search(name)
        if found_prefix:
            base_name = found_prefix.group(2)

        #remove -pythonXY like suffix if present
        found_end = self.reg_end.search(name.lower())
        if found_end:
            base_name = found_end.group(1)

        return base_name


class NameVariants(object):
    """Class to generate variants of python package name and choose
    most likely correct one.
    """

    def __init__(self, name, version):
        self.name = name
        self.version = version
        self.python_ver_name = 'python{0}-{1}'.format(self.version, self.name)
        self.pyver_name = name if self.name.startswith('py') else 'py{0}{1}'.format(
                self.version, self.name)
        self.name_python_ver = '{0}-python{1}'.format(self.name, self.version)
        self.raw_name = name

        self.name_variants = {'python_ver_name': None,
                         'pyver_name': None,
                         'name_python_ver': None,
                         'raw_name': None}

    def find_match(self, name):
        for variant in ['python_ver_name', 'pyver_name', 'name_python_ver', 'raw_name']:
            # iterates over all variants and store name to name_variants if matches
            if canonical_form(name) == canonical_form(getattr(self, variant)):
                self.name_variants[variant] = name

    def merge(self, other):
        """Merges object with other NameVariants object, not set values 
        of self.name_variants are replace by values from other object.
        """
        if not isinstance(other, NameVariants):
            raise TypeError("NameVariants isinstance can be merge with"
                    "other isinstance of the same class")
        for key in self.name_variants:
            self.name_variants[key] = self.name_variants[key] or other.name_variants[key]
        
        return self

    @property
    def best_matching(self):
        return (self.name_variants['python_ver_name'] or
                self.name_variants['pyver_name'] or
                self.name_variants['name_python_ver'] or
                self.name_variants['raw_name'])


class DandifiedNameConvertor(NameConvertor):
    """Name convertor based on DNF API query, checks if converted
    name of the package exists in Fedora repositories. If it doesn't, searches
    for the correct variant of the name.
    """

    def __init__(self, *args):
        super(DandifiedNameConvertor, self).__init__(*args)
        with dnf.Base() as base:
            base.read_all_repos()
            base.fill_sack()
            self.query = base.sack.query()

    def rpm_name(self, name, python_version=None):
        """Checks if name converted using superclass rpm_name_method match name
        of package in the query. Searches for correct name if it doesn't.
        """
        original_name = name
        converted = super(DandifiedNameConvertor, self).rpm_name(name, python_version)
        python_query = self.query.filter(name__substr=['python', 'py', original_name,
            canonical_form(original_name)])
        print("Converted {}".format(converted))
        if converted in [pkg.name for pkg in python_query]:
            print("Converted matches")
            return converted

        print("Searches for correct name")
        not_versioned_name = NameVariants(self.base_name(original_name), '')
        versioned_name = NameVariants(self.base_name(original_name), python_version)
        for pkg in python_query:
             versioned_name.find_match(pkg.name)
             not_versioned_name.find_match(pkg.name)

        print(versioned_name.name_variants)
        print(not_versioned_name.name_variants)
        return versioned_name.merge(not_versioned_name).best_matching


def canonical_form(name):
    return name.lower().replace('-', '_')
