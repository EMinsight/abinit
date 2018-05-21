#!/usr/bin/env python
# coding: utf-8
"""
Parser for warning messages emitted by Fortran compilers.
"""
from __future__ import print_function, division, unicode_literals

import sys
import os
import io
import re
import abc

from collections import Counter, OrderedDict
from tools import pprint_table, lazy_property

# From https://gcc.gnu.org/onlinedocs/gfortran/Error-and-Warning-Options.html#Error-and-Warning-Options
#
# -Wall
# Enables commonly used warning options pertaining to usage that we recommend avoiding and that we believe are easy to avoid.
# This currently includes
#  -Waliasing, -Wampersand, -Wconversion, -Wsurprising, -Wc-binding-type, -Wintrinsics-std, -Wtabs,
#  -Wintrinsic-shadow, -Wline-truncation, -Wtarget-lifetime, -Winteger-division, -Wreal-q-constant and -Wunused.

GNU_WARNINGS = {  # kind --> info
"-Waliasing":
"""Warn about possible aliasing of dummy arguments. Specifically, it warns if the same actual argument is associated
with a dummy argument with INTENT(IN) and a dummy argument with INTENT(OUT) in a call with an explicit interface.
The following example will trigger the warning.

            interface
              subroutine bar(a,b)
                integer, intent(in) :: a
                integer, intent(out) :: b
              end subroutine
            end interface
            integer :: a

            call bar(a,a)""",

"-Wampersand":
"""Warn about missing ampersand in continued character constants. The warning is given with
-Wampersand, -pedantic, -std=f95, -std=f2003 and -std=f2008.
Note: With no ampersand given in a continued character constant, GNU Fortran assumes continuation at the first non-comment,
non-whitespace character after the ampersand that initiated the continuation.""",

"-Warray-temporaries":
"""Warn about array temporaries generated by the compiler. The information generated by this warning is sometimes
useful in optimization, in order to avoid such temporaries.""",

"-Wc-binding-type":
"""Warn if the a variable might not be C interoperable. In particular, warn if the variable has been declared
using an intrinsic type with default kind instead of using a kind parameter defined for C interoperability
in the intrinsic ISO_C_Binding module. This option is implied by -Wall.""",

"-Wcharacter-truncation":
"""Warn when a character assignment will truncate the assigned string.""",

"-Wline-truncation":
"""Warn when a source code line will be truncated. This option is implied by -Wall.
For free-form source code, the default is -Werror=line-truncation such that truncations are reported as error.""",

"-Wconversion":
"""Warn about implicit conversions that are likely to change the value of the expression after conversion. Implied by -Wall. """,

"-Wconversion-extra":
"""Warn about implicit conversions between different types and kinds. This option does not imply -Wconversion.""",

"-Wextra":
"""Enables some warning options for usages of language features which may be problematic.
This currently includes -Wcompare-reals and -Wunused-parameter.""",

"-Wimplicit-interface":
"""Warn if a procedure is called without an explicit interface. Note this only checks that an explicit interface is present.
It does not check that the declared interfaces are consistent across program units.""",

"-Wimplicit-procedure":
"""Warn if a procedure is called that has neither an explicit interface nor has been declared as EXTERNAL.""",

"-Winteger-division":
"""Warn if a constant integer division truncates it result. As an example, 3/5 evaluates to 0.""",

"-Wintrinsics-std":
"""Warn if gfortran finds a procedure named like an intrinsic not available in the currently selected standard (with -std)
and treats it as EXTERNAL procedure because of this. -fall-intrinsics can be used to never trigger this behavior and always
link to the intrinsic regardless of the selected standard.""",

"-Wreal-q-constant":
"Produce a warning if a real-literal-constant contains a q exponent-letter.",

"-Wsurprising":
"""Produce a warning when “suspicious” code constructs are encountered. While technically legal these usually indicate
that an error has been made. This currently produces a warning under the following circumstances:

    An INTEGER SELECT construct has a CASE that can never be matched as its lower value is greater than its upper value.
    A LOGICAL SELECT construct has three CASE statements.
    A TRANSFER specifies a source that is shorter than the destination.
    The type of a function result is declared more than once with the same type. If -pedantic or standard-conforming mode is enabled, this is an error.
    A CHARACTER variable is declared with negative length.""",

"-Wtabs":
"""By default, tabs are accepted as whitespace, but tabs are not members of the Fortran Character Set.
For continuation lines, a tab followed by a digit between 1 and 9 is supported. -Wtabs will cause a warning to be issued
if a tab is encountered. Note, -Wtabs is active for -pedantic, -std=f95, -std=f2003, -std=f2008, -std=f2008ts and -Wall.""",

"-Wunderflow":
"""Produce a warning when numerical constant expressions are encountered, which yield an UNDERFLOW during compilation.
Enabled by default.""",

"-Wintrinsic-shadow":
"""Warn if a user-defined procedure or module procedure has the same name as an intrinsic; in this case, an explicit interface
or EXTERNAL or INTRINSIC declaration might be needed to get calls later resolved to the desired intrinsic/procedure.
This option is implied by -Wall.""",

"-Wuse-without-only":
"Warn if a USE statement has no ONLY qualifier and thus implicitly imports all public entities of the used module.",

"-Wunused-dummy-argument": "Warn about unused dummy arguments. This option is implied by -Wall.",

"-Wunused-parameter":
"""Contrary to gcc's meaning of -Wunused-parameter, gfortran's implementation of this option does not warn about
unused dummy arguments (see -Wunused-dummy-argument), but about unused PARAMETER values.
-Wunused-parameter is implied by -Wextra if also -Wunused or -Wall is used.""",

"-Walign-commons":
"""By default, gfortran warns about any occasion of variables being padded for proper alignment inside a COMMON block.
This warning can be turned off via -Wno-align-commons. See also -falign-commons.""",

"-Wfunction-elimination":
"Warn if any calls to functions are eliminated by the optimizations enabled by the -ffrontend-optimize option.",

"-Wrealloc-lhs":
"""Warn when the compiler might insert code to for allocation or reallocation of an allocatable array variable
of intrinsic type in intrinsic assignments. In hot loops, the Fortran 2003 reallocation feature may reduce the performance.
If the array is already allocated with the correct shape, consider using a whole-array array-spec (e.g. (:,:,:))
for the variable on the left-hand side to prevent the reallocation check.
Note that in some cases the warning is shown, even if the compiler will optimize reallocation checks away.
For instance, when the right-hand side contains the same variable multiplied by a scalar. See also -frealloc-lhs.""",

"-Wrealloc-lhs-all":
"""Warn when the compiler inserts code to for allocation or reallocation of an allocatable variable;
this includes scalars and derived types.""",

"-Wcompare-reals":
"""Warn when comparing real or complex types for equality or inequality. This option is implied by -Wextra.""",

"-Wtarget-lifetime":
"""Warn if the pointer in a pointer assignment might be longer than the its target. This option is implied by -Wall.""",

"-Wzerotrip":
"""Warn if a DO loop is known to execute zero times at compile time. This option is implied by -Wall.""",

"-Werror": "Turns all warnings into errors.",

# These types are not documented
"-Wunused-value": "FIXME",
"-Wunused-variable": "FIXME",
"-Wunused-function":  "FIXME",

#
"GnuExtension": "FIXME",
"Obsolescent": "Obsolescent Feature",
}

class Message(object):
    """
    .. attributes:

        filepath:
        lineno:
        colno:
        text:
    """
    def __init__(self, filepath, kind, text, lineno, colno, info):
        self.filepath = filepath if filepath is not None else "Unknown"
        self.kind = kind
        self.text = text
        self.lineno = int(lineno) if lineno is not None else 0
        self.colno = int(colno) if colno is not None else 0
        self.info = info

    @lazy_property
    def filename(self):
        return os.path.basename(self.filepath)

    @lazy_property
    def dirname(self):
        return os.path.basename(os.path.dirname(self.filepath))

    def __repr__(self):
        return "<%s at %s +%d>" % (self.kind, self.filepath, self.lineno)

    def __str__(self):
        return self.text


class GFortranWarning(Message):
    """
../../../src/98_main/mrgscr.F90:1852:25:

        omega_new = CMPLX(-one,-one)
                         1
Warning: Conversion from REAL(8) to default-kind COMPLEX(4) at (1) ... [-Wconversion]

../../../src/53_ffts/m_fft.F90:1606:47: Warning: Possible change of ... at (1) [-Wconversion]

../../../src/01_linalg_ext/m_linalg_interfaces.F90:84:14:

    character*1 :: TRANS
              1
Warning: Obsolescent feature: Old-style character length at (1)

../../../src/28_numeric_noabirule/interfaces_28_numeric_noabirule.F90:705:8:

real*8, intent(inout) :: a(mesh)
1
Warning: GNU Extension: Nonstandard type declaration REAL*8 at (1)

../../../src/95_drive/eph.F90:320:54: Warning: Possible change of value in ... at (1) [-Wconversion]
    """
    def __init__(self, lines):
        text = "\n".join(lines) #.encode("utf8")

        if len(lines) > 1:
            filepath, lineno, colno, _ = lines[0].split(":")
            last = lines[-1]

            if last.startswith("Warning: GNU Extension:"):
                kind = "GnuExtension"
            elif last.startswith("Warning: Obsolescent feature:"):
                kind = "Obsolescent"
            else:
                kind = last.split()[-1].replace("[", "").replace("]", "")

        else:
            tokens = lines[0].split()
            filepath, lineno, colno, _ = tokens[0].split(":")
            kind = tokens[-1].replace("[", "").replace("]", "")

        info = GNU_WARNINGS.get(kind)
        if info is None:
            raise RuntimeError("Cannot find kind: %s in GNU_WARNINGS" % kind)

        super(self.__class__, self).__init__(filepath, kind, text, lineno, colno, info)


class WarningsParser(object):

    def __init__(self):
        self.warns = []
        self.filepaths = "Unknown"

    @classmethod
    def from_compiler(cls, compiler):
        for c in cls.__subclasses__():
            if c.compiler == compiler: return c()
        raise ValueError("No Parser associated to compiler `%s`" % compiler)

    @abc.abstractmethod
    def parse_lines(self, lines, filepath="Unknown"):
        """Parse the file. Returns self."""

    def parse_file(self, filename):
        self.filepath = os.path.abspath(filename)
        with io.open(filename, "rt", encoding="utf8") as fh:
            return self.parse_lines(fh.readlines(), filepath=self.filepath)

    @property
    def num_warns(self):
        return len(self.warns)


    def __repr__(self):
        return "<%s %s: num_warns: %s>" % (self.__class__.__name__, self.filepath, self.num_warns)

    def __str__(self):
        return self.to_string()

    def to_string(self, verbose=0):
        lines = ["<%s %s: num_warns: %s>" % (self.__class__.__name__, self.filepath, self.num_warns), ""]
        lines.append(self.summarize())
        return "\n".join(lines)

    def summarize(self):
        """Return string with data in tabular form."""
        counter = Counter(warn.kind for warn in self.warns)
        table = [["Kind", "Count"]]
        for kind, num in counter.most_common():
            table.append([str(kind), str(num)])

        try:
            from io import StringIO
        except ImportError:
            from StringIO import StringIO
        out = StringIO()
        pprint_table(table, out=out)
        return out.getvalue()

    #def groupby_file(self):
    #    od = OrderedDict()
    #    for w in self.warns:
    #        if w.filename not in od: od[w.filename] = []
    #        od[w.filename].append(w)
    #    return od

    #def groupby_kind(self):
    #    od = OrderedDict()
    #    for w in self.warns:
    #        if w.kind not in od: od[w.kind] = []
    #        od[w.kind].append(w)
    #    return od


class GfortranParser(WarningsParser):
    compiler = "gfortran"

    def parse_lines(self, lines, filepath="Unknown"):
        buff = []
        for line in lines:
            line = line.strip()
            if "Warning: " in line:
            #if line.startswith("Warning: "):
                #print(line)
                buff.append(line)
                try:
                    self.warns.append(GFortranWarning(buff))
                except Exception:
                    print("\n".join(buff))
                    raise
                buff = []
            else:
                buff.append(line)

        assert not buff
        #if buff:
        #    self.warns.append(GFortranWarning(buff))
        #    buff = []

        return self


# Intel uses numbers to identify remarks and warnings.

# ../../../src/17_libtetra_ext/m_tetrahedron.F90(1119): warning #6843: A dummy argument ... explicit value.   [TWEIGHT]
RE_IFORT_WARN = re.compile(r"(?P<filepath>.+)\((?P<lineno>\d+)\):\s+warning\s+#(?P<kind>\d+):\s*(?P<info>\w*)")

# icc: command line remark #10010: option
RE_IFORT_REMARK = re.compile(r".+command line remark\s+#(?P<kind>\d+):\s*(?P<info>\w*)")


class IfortRemark(Message):

    def __init__(self, line):
        m = RE_IFORT_REMARK.match(line)
        if not m:
            raise ValueError("String does not match regex: %s" % line)

        super(self.__class__, self).__init__(filepath=None, kind=m.group("kind"), text=line,
            lineno=None, colno=None, info=m.group("info"))


class IfortWarning(Message):

    def __init__(self, lines):
        m = RE_IFORT_WARN.match(lines[0])
        if not m:
            raise ValueError("String does not match regex: %s" % lines[0])

        super(self.__class__, self).__init__(
            filepath=m.group("filepath"), kind=m.group("kind"), text="\n".join(lines),
            lineno=m.group("lineno"), colno=None, info=m.group("info"))


class IfortParser(WarningsParser):
    compiler = "ifort"

    def parse_lines(self, lines, filepath="Unknown"):
        """
        icc: command line remark #10010: option '-vec-report0' is deprecated and will be removed ...
        """
        buff = []
        for line in lines:
            line = line.strip()

            if "command line remark #" in line:
                self.warns.append(IfortRemark(line))
                continue

            if "warning #" in line:
                if buff:
                    self.warns.append(IfortWarning(buff))
                buff = [line]
            else:
                buff.append(line)

        if buff:
            self.warns.append(IfortWarning(buff))
            buff = []

        assert not buff
        return self


def main():
    filepath = sys.argv[1]
    compiler = "gfortran" if "intel" not in filepath else "ifort"
    parser = WarningsParser.from_compiler(compiler).parse_file(filepath)
    print(parser.to_string(verbose=0))

    # Define set of ignored warnings.
    if parser.compiler == "gfortran":
        ignored_kinds = set([
            "-Wimplicit-interface",
            "-Wconversion",
        ])

    elif parser.compiler == "ifort":
        ignored_kinds = set([
        ])

    else:
        raise ValueError("Missing ignored_kinds for compiler %s" % parser.compiler)

    retcode = 0
    for warn in parser.warns:
        if warn.kind in ignored_kinds: continue
        #print(warn)
        retcode += 1

    return retcode


if __name__ == "__main__":
    sys.exit(main())