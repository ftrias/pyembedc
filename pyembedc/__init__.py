#
# Copyright 2010-2018 by Fernando Trias. All rights reserved.
# See LICENSE for Open Source details.
#

"""pyembedc Embed C/C++ code in Python source code

pyembedc enables Python source code to embed C/C++ snippets that seamlessly
access and modify Python variables and call Python functions. 

Simple example:

    from pyembedc import C
    v = 5
    r = C('''
        v = v * 10;
        ''')
    print(v)

Complex example:

    from pyembedc import C

    def myround(number):
        return round(number, 1)

    def test(data):
        datalen = len(data)
        mean = 0.0
        stddev = 0.0
        status="Calculate statistics"
        C('''
            #include <math.h>
            DEF double myround double
            printf("%s: ", status);
            double sum, sumsq = 0.0;
            for(int i=0;i<datalen; i++) {
                sum += data[i];
            }
            mean = sum / datalen;
            for(int i=0;i<datalen; i++) {
                sumsq += pow((data[i] - mean),2);
            }
            stddev = sqrt(sumsq / (datalen-1));
            stddev = myround(stddev);
            mean = myround(mean);
            status = "Done";
            ''')
        print("Mean = %f" % mean)
        print("Stddev = %f" % stddev)
        print(status)

    samples=(10.5,15.1,14.6,12.3,19.8,17.1,6.1)
    test(samples)
    
"""

import inspect
import ctypes
import os
import tempfile
import subprocess
import platform
import re

# GLOBALS
#
# Dictionary with list of files that have been "compiled"
processed = {}

# Dictionary that holds pointers to function names in a DLL/SO 
# corresponding to source file/line number
savefunc = {}

# hash of CDLL objects for each source file
mylib = {}

# default compiler to use
cc = ""

# other global variables are scattered through the code where they are need. 
# In addition, there is some initilization at the end

#
# class deletes temporary DLL/SO files. Unfortunately, ctypes has functions 
# for loading DLL/SOs, but not for unloading them. Thus deletion must 
# occur at program termination.
#
class _AutoCleanup:
    def __init__(self):
        self.files = []
        self.unloadlib = []
    def add(self, file):
        self.files.append(file)
    def unload(self, dll):
        self.unloadlib.append(dll)
    def __del__(self):
        for path in self.files:
            try:
                os.remove(path)
            except:
                continue
        del self.files
        for dll in self.unloadlib:
            try:
                _unload_library(dll)
            except:
                continue
        del self.unloadlib
        
_cleanup = _AutoCleanup()

def _unload_library(tdll):
    if windows:
        ctypes.cdll.kernel32.FreeLibrary(tdll._handle)
    else:
        libdl = ctypes.CDLL("libdl.so")
        libdl.dlclose(tdll._handle)

#
# this class and _savelocals function access internal Python objects to 
# save the local variables. This code is delicate. If the structure changes
# it could crash python
#        
class _CPyFrame(ctypes.Structure):
    pass   
_CPyFrame._fields_ = [
                 ("refcount", ctypes.c_int),
                 ("p_objtype", ctypes.c_void_p),
                 ("size", ctypes.c_int),
                 ("p_back", ctypes.POINTER(_CPyFrame))
                ]
                
def _is_CPyFrame_bad(frameptr):
    if frameptr is None or frameptr == 0:
        raise SaveLocalsError("PyEval_GetFrame() frame pointer is NULL")       
    try:
        if frameptr[0].refcount > 100 or frameptr[0].refcount < 1:
            raise SaveLocalsError("PyEval_GetFrame() refcount too large or small (count=%d)" % frameptr[0].refcount)
    except:
        raise SaveLocalsError("PyEval_GetFrame() frame is invalid or empty")
    if frameptr[0].size > 50 or frameptr[0].size < 0:
        raise SaveLocalsError("PyEval_GetFrame() frame is too large or small, possibly invalid (size=%d)" % frameptr[0].size)
    return False

class SaveLocalsError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)
        
def _savelocals(frame, testmode=0):
    if frame is None:
        raise SaveLocalsError("Frame passed to _savelocals is None")
    # count frames we have to go back, up to 10 levels
    found = -1
    testframe = inspect.currentframe()
    for i in range(10):
        testframe = testframe.f_back
        if testframe is frame:
            found = i+1
            break
    # if we haven't found our frame, there's a big problem but for now
    # I'm not sure what to do about it
    if found<0:
        raise SaveLocalsError("Could not find context frame while saving local variables")
    else:
        # get current frame into our structure
        try:
            # this is only for test.py
            if testmode == 1: api = ctypes.pythonapi.PyEval_GetFrameXYZ
            api = ctypes.pythonapi.PyEval_GetFrame
        except AttributeError:
            raise SaveLocalsError("Could not find PyEval_GetFrame() function")
            
        api.restype = ctypes.POINTER(_CPyFrame)
        frameptr = api()
        
        #  this is only used by test.py to make sure sanity checks are covered in testing
        if testmode == 2: frameptr = None
        if testmode >= 3:
            frameptr = [_CPyFrame()]
            if testmode == 4: frameptr[0].refcount = 50000
            if testmode == 5: 
                frameptr[0].refcount = 1
                frameptr[0].size = 10000
        
        # now some sanity checks to prevent a hard crash in case the structure has changed
        _is_CPyFrame_bad(frameptr)

        # now loop as many times as we have to go back in each call frame
        for i in range(found):
            frameptr = frameptr[0].p_back
            _is_CPyFrame_bad(frameptr)
        ctypes.pythonapi.PyFrame_LocalsToFast(frameptr, 0)
    return True

class EmbedParseError(Exception):
    def __init__(self, value):
        self.value = value
    def __str__(self):
        return repr(self.value)
    
class _CodeFragment:
    funcname = "func"
    sourcecode = [""]
    arguments = []
    variables = []
    rettype = ""
    prefunc = []
    postfunc = []
    lineno = 0
    gcc = cc
    inline = False
        
    def type2c(self, t, const=False):
        """Convert our c-like type definitions in the valid C syntax"""
        if t.endswith("[]"):
            t = t.replace("[]", "*")
        if t == "string" or t == "str":
            typ = "const char*"
        elif t == "string*" or t == "str*":
            typ = "const char**"
        elif t == "ustring" or t == "ustr":
            typ = "const wchar_t*"
        elif t == "ustring*" or t == "ustr*":
            typ = "const wchar_t**"
        elif t == "voidp" or t == "void*":
            typ = "void*"
        else:
            typ = "%s" % t
        if const:
            typ = "const %s" % typ
        return typ
        
    def write_func(self, fpo, pfuncname=""):
        """Write the code framgment to file fpo, which should be an open file"""
        if pfuncname != "":
            self.funcname = pfuncname
        arglist = []
        for i in range(len(self.arguments)):
            arglist.append(self.type2c(
                self.arguments[i])+" "+self.variables[i])
        fpo.write("\n".join(self.prefunc))
        fpo.write("\nextern \"C\" {\n")
        if self.inline:
            fpo.write("%s %s(%s) {" % 
                (self.type2c(self.rettype), self.funcname, ",".join(arglist)))
        fpo.write("\n".join(self.sourcecode))
        if self.inline:
            fpo.write("\n}\n")
            fpo.write("void %s_post() {\n" % self.funcname)
            fpo.write("\n".join(self.postfunc))
            fpo.write("\n}\n")
        fpo.write("\n}  //extern C\n")
        fpo.write("\n")
        return self.funcname
        
    def _sanitize_filename(self, file):
        if file.find("\\\\") >= 0: # already converted
            return file
        if file.find("\\") >= 0:
            return file.replace("\\", "\\\\")
        return file

    def _parse_import_line(self, line):
        items = self._clean_up_import_line(line).split()
        if len(items) == 3:
            return items
        else:
            raise EmbedParseError("Invalid IMPORT syntax '%s'" % line)

    def _clean_up_import_line(self, line):
        line = re.sub(r'\&\s+', ' &', line)
        line = re.sub(r'\s+\*', '* ', line)
        line = re.sub(r'\s+\[\]', '[] ', line)
        line = re.sub(r'\[\]\&', '[] &', line)
        return line
        
    def parse_embed_code(self, filename, lineno, source, inline):
        """Take source code and parse out directives, imports, etc."""
        self.importall = False
        self.arguments = []
        self.variables = []
        self.functions = {}
        self.sourcecode = [""]
        self.prefunc = [
            "#include <string.h>",
            "#include <stdio.h>",
            "#include <stdlib.h>"]
        self.postfunc = []
        self.rettype = "int"
        self.gcc = cc
        self.inline = inline
        self.lineno = lineno
        
        subline = lineno-len(source)-1
        
        importspec = False

        basefile = self._sanitize_filename(filename)

        self.prefunc.append('#line %d "%s"' % (subline, basefile))
        for line in source:
            subline += 1
            try:
                directive = line.strip().split()[0]
            except IndexError:
                continue
            
            if directive.startswith("#"):
                self.prefunc.append("#line %d" % subline)
                self.prefunc.append(line)
                continue
            if directive == "GLOBAL":
                exp = line.replace("GLOBAL","", 1).strip()
                self.prefunc.append("#line %d" % subline)
                self.prefunc.append(exp)
                continue
            if directive == "CC":
                self.gcc = line.replace("CC","", 1).strip()
                continue
            if directive == "IMPORTALL":
                self.importall = True
                continue
            if directive == "IMPORT":
                importspec = True
                (cmd, typ, var) = self._parse_import_line(line)
                self.arguments.append(typ)
                self.variables.append(var.replace(";",""))
                continue
            if directive == "DEF":
                args = line.split()
                rettype = args[1]
                funcname = args[2]
                args = args[3:]
                funcx = "func_ptr_%s" % funcname
                self.functions[funcx] = (rettype, funcname, args)
                cargstr = ", ".join(map(self.type2c, args))
                rettype = self.type2c(rettype)
                self.sourcecode.append("#line %d" % subline)
                self.arguments.append("void*")
                self.variables.append("func_ptr_%s" % funcname)
                self.sourcecode.append("""
                        %s (*%s)(%s);
                        %s = (%s (*)(%s))%s;
                        """ % (rettype, funcname, cargstr, funcname, 
                            rettype, cargstr, funcx))
                continue
            if directive == "RETURN":
                line = re.sub(r'\s*RETURN\s+', '', line)
                (rtype, stxt, exp) = line.partition(' ')
                self.rettype = rtype.strip()
                self.sourcecode.append("#line %d" % subline)
                self.sourcecode.append("return %s;" % exp.strip())
                continue
            if directive == "POST":
                exp = line.replace("POST","", 1)
                self.postfunc.append("#line %d" % subline)
                self.postfunc.append(exp)
                continue
            self.sourcecode.append("#line %d" % subline)
            self.sourcecode.append(line)
            
        # if there's no IMPORT line, import all variables
        if not importspec and not self.importall:
            self.importall = True
            
        return True

        
class _CodeFile:
    def need_reload(self, file):
        """Check file times to see if we need to recompile because source file has changed"""
        s1 = os.stat(file)
        dll = _get_dll_name(file)
        try:
            s2 = os.stat(dll)
        except:
            return True
        if s1.st_mtime > s2.st_mtime:
            return True
        return False

    def parse_file(self, file):
        """Read entire file and extract"""
        funcnum = 0
        newer = self.need_reload(file)
        comp = _EmbedCompile()
        gcc = ""
        if newer:
            fpo = open("%s.cpp" % file, "w")
            fpo.write("//%s\n" % file)
        for code in self.parse_file_next(file):
            funcnum+=1
            code.funcname = "func_%d" % funcnum
            savefunc[(file, code.lineno)] = code
            gcc = code.gcc
            if newer:
                code.write_func(fpo)
        if newer:
            fpo.close()
            comp.compile(file, gcc)
        global mylib
        if file not in mylib:
            self._load_file_into_library(file)
            
    def _load_file_into_library(self, file):
            dll = _get_dll_name(file)
            ctypes.cdll.LoadLibrary(dll)
            mylib[file] = ctypes.CDLL(dll)
            _cleanup.unload(mylib[file])

    def parse_file_next(self, file):
        fp = open(file, "r")
        lineno=0
        infunc = False
        inline = False
        for line in fp:
            lineno += 1
            if line.find("_c_precompile"):
                if infunc == False and line.strip().startswith("#"):
                    continue
                if line.find("inline_c_precompile(\"\"\"")>=0:
                    infunc = True
                    inline = True
                    funcx = []
                    continue
                if line.find("embed_c_precompile(\"\"\"")>=0:
                    infunc = True
                    inline = False
                    funcx = []
                    continue
            if infunc:
                if line.find("\"\"\"")>=0:
                    code = _CodeFragment()
                    code.parse_embed_code(file, lineno, funcx, inline)
                    yield code
                    infunc = False
                    inline = False
                else:
                    funcx.append(line.rstrip())
        fp.close()

def _type2ctype(t, ev=False):
    if t == "string" or t == "str":
        typ = "ctypes.c_char_p"
    elif t == "ustring":
        typ = "ctypes.c_wchar_p"
    elif t == "void*" or t == "voidp":
        typ = "ctypes.c_void_p"
    elif t == "float64":
        typ = "ctypes.c_float"
    elif t == "int64":
        typ = "ctypes.c_int"
    else:
        typ = "ctypes.c_%s" % t
    if ev:
        return eval(typ)
    else:
        return typ

def _get_caller_info(levels=1):
    fr = inspect.currentframe()
    for i in range(levels+1):
        fr  = fr.f_back
    (filename, lineno, function, code_context, index) = inspect.getframeinfo(fr)
    return (fr, filename, lineno)
        
def C(source):
    """Compile at runtime and run code in-line"""
    return _embed_or_inline_c(source, True)
        
def inline_c_precompile(source):
    """Precompile C/C++ code and run it in-line"""
    fr = inspect.currentframe().f_back
    (lib, code) = _load_func(fr)
    return _call_func(lib, code, fr)

def inline_c(source):
    """Compile at runtime and run code in-line"""
    return _embed_or_inline_c(source, True)
    
def embed_c_precompile(source):
    """Precompile and load C functions; return CDLL object"""
    fr = inspect.currentframe().f_back
    (lib, source) = _load_func(fr)
    return lib

def embed_c(source):
    """Compile and load C functions; return CDLL object"""
    return _embed_or_inline_c(source, False)

def _embed_or_inline_c(source, inline, filename=None, lineno=0):
    """Compile and load C code, but don't execute; return CDLL object"""
    code = _CodeFragment()
    comp = _EmbedCompile()
    sourcecode = source.split("\n")
    if filename is None:
        (fr, filename, lineno) = _get_caller_info(2)
    code.parse_embed_code(filename, lineno+1, sourcecode, inline)
    fr = inspect.currentframe().f_back.f_back
    _import_all_vars(code, fr)
    (dll, func) = comp.temp_compile(code)
    tdll = ctypes.cdll.LoadLibrary(dll)
    _cleanup.unload(tdll)
    if inline:
        r = _call_func(tdll, code, fr)
        return r
    return tdll

# Helper funcitons
def array(x, c_type=None):
  if c_type == None:
    c_type = _type2ctype(type(x[0]).__name__, True)
  return (c_type * len(x))(*x)

# Getting frame info is slow on Windows
def _get_source(fr):
    lineno = inspect.getframeinfo(fr)[1]
    sourcepath = os.path.abspath( inspect.getsourcefile( fr.f_code ) )
    return sourcepath, lineno
    
def _load_func(fr):
    (sourcepath, lineno) = _get_source(fr)
    _load_func_parse(sourcepath)
    lib = mylib[sourcepath]
    code = savefunc[sourcepath, lineno]
    return lib, code

def _load_func_parse(sourcepath):    
    global processed
    if sourcepath not in processed:
        _CodeFile().parse_file(sourcepath)
        processed[sourcepath] = True

_ustringtype = None
_ispython3 = None

def _is_3():
    # test python 2.6 & 3.0
    global _ustringtype
    global _ispython3
    if _ustringtype is None:
        _ispython3 = False
        try:
            _ustringtype = unicode  # fails on 3.0+
            _ispython3 = False
        except NameError:
            _ustringtype = type('')
            _ispython3 = True
    return _ispython3
        
def _isunicode(text):
    # test python 2.6 & 3.0
    _is_3()
    if type(text) is _ustringtype:
        return True
    else:
        return False

def _is_in_list(L, value):
    try:
        L.index(value)
        return True
    except ValueError:
        return False

def _import_all_vars_dict(code, varlist):
    for k, v in varlist.items():
        if k.startswith("_"):
            continue
        if _is_in_list(code.variables, k):
            continue
        tt = v.__class__.__name__
        ex1 = ""
        ex2 = ""
        if tt == "list" or tt == "tuple":
            ex1 = "[]"
            if len(v)>0:
                tt = v[0].__class__.__name__
            else:
                tt = "int"
        else:
            ex2 = "&"
        
        if tt == "str":
            tt = "string"
        else:
            try:
                eval("ctypes.c_%s()" % tt)
            except:
                # no equivalent in ctypes, so ignore this variable
                continue
                
        if _is_in_list(code.variables, ex2+k):
            continue
        code.arguments.append(tt+ex1)
        code.variables.append(ex2+k)

def _import_all_vars(code, frame):        
    if code.importall:
        _import_all_vars_dict(code, frame.f_locals)
        _import_all_vars_dict(code, frame.f_globals)
        
def _call_func(dll, code, fr):
    f = getattr(dll, code.funcname)
    f.argtypes = []
    f.restype = _type2ctype(code.rettype, True)
    value = []
    unicodetype = []
    local = []

    for v in range(len(code.variables)):
        if code.variables[v].find("&") >= 0:
            ref = True
            varname = code.variables[v].replace("&","")
        else:
            ref = False
            varname = code.variables[v]

        vardata = 0
        islocal = False

        if code.variables[v].startswith("func_ptr"):
            funcx = code.variables[v]
            (rettype, funcname, argtypes) = code.functions[funcx]
            parglist = [_type2ctype(rettype, True)]
            for arg in argtypes:
                parglist.append(_type2ctype(arg, True))
            FUNC = ctypes.CFUNCTYPE(*parglist)
            vardata = FUNC(fr.f_globals[funcname])
            #vardata = eval("FUNC(%s)" % (funcname))
        else:
            try:
                vardata = fr.f_locals[varname]
                islocal = True
            except:
                vardata = fr.f_globals[varname]

        value.append(vardata)
        local.append(islocal)
        unicodetype.append(_isunicode(vardata))
        
        if code.arguments[v].endswith("[]"):
            tt = code.arguments[v].rstrip("[]")
            f.argtypes.append(ctypes.POINTER(_type2ctype(tt, True) * len(value[v])))
            if type(value[v]) is not _type2ctype(tt, True):
                evalstr = "(%s * %d)(*value[v])" % (_type2ctype(tt), len(value[v]))
                value[v] = eval(evalstr)
            continue

        tt = _type2ctype(code.arguments[v], True)

        if type(value[v]) == str:
            try:
              value[v] = tt(value[v].encode('utf-8'))
            except:
              pass

        if ref:
            f.argtypes.append(tt)
            if type(value[v]) is not tt:
                value[v] = ctypes.byref(tt(value[v]))
            else:
                value[v] = ctypes.byref(value[v])
            continue

        if tt is ctypes.c_void_p:
            f.argtypes.append(tt)
            continue

        f.argtypes.append(tt)

        if type(value[v]) is not tt:
            try:
                value[v] = tt(value[v])
            except:
                raise EmbedParseError("Problem converting '%s' to '%s' '%s'" % (value[v], tt, code.arguments[v]))
        
    r = f(*value)
        
    for v in range(len(code.variables)):
        if code.variables[v].find("&") >= 0:
            varname = code.variables[v].replace("&","")
            val = value[v]._obj.value
            if not _isunicode(val) and unicodetype[v]:
                val = val.decode('ascii')
            if local[v]:
                fr.f_locals[varname] = val
                _savelocals(fr)
            else:
                fr.f_globals[varname] = val
        if code.arguments[v].endswith("[]"):
            varname = code.variables[v]
            vals = []
            for i in value[v]:
                vals.append(i)
            if local[v]:
                if not _is_tuple(fr.f_locals[varname]):
                    fr.f_locals[varname] = vals
                    _savelocals(fr)
            else:
                if not _is_tuple(fr.f_globals[varname]):
                    fr.f_globals[varname] = vals
    
    if code.rettype == "string":
        r = r.decode('ascii')
        
    f = getattr(dll, "%s_post" % code.funcname)
    if f is not None:
        f()
    return r
    
def _is_tuple(x):
    if type(x) is type(()):
        return True
    return False

def _get_dll_name(file):
    return "%s.cpp.%s" % (file, dllext)

def _convert_to_ascii(list):
    if _is_3(): # 3.0+ is already unicde, so ignore
        return list
    # for other version, rencode
    rlist = []
    for i in list:
        rlist.append(i.decode('ascii', 'ignore').encode('ascii'))
    return rlist
    
class EmbedCompileError(Exception):
    def __init__(self, value, ret, gcc, options, output):
        self.value = value
        self.ret = ret
        self.gcc = gcc
        self.options = options
        self.output = output
    def __str__(self):
        return repr([self.value, self.ret, self.gcc, self.options, self.output])

class _EmbedCompile:
    def testcc(self):
        global cc
        if cc != "":
            return True
        opt="--version"
        ret = 0
        cclist = ("gcc", "clang")
        output=""
        for cmd in cclist:
            try:
                (ret, output) = self.run_capture([cmd, opt])
                if ret == 0:
                    cc = cmd
                    return True
            except:
                pass
        raise EmbedCompileError("C compiler not found or configured", ret, cclist, opt, output)

    def run_capture(self, command):
        (out, filepath) = tempfile.mkstemp(".log")
        # print("RUN", command)
        try:
            p = subprocess.Popen(command, stdout=out, stderr=out)
            ret = p.wait()
        except:
            try:
                os.close(out)
                os.remove(filepath)
            except:
                pass
            raise
            
        os.close(out)
        fp = open(filepath, "r")
        output = fp.readlines()
        output = _convert_to_ascii(output)
        fp.close()
        os.remove(filepath)
        return (ret, output)
        
    def compile(self, file, gcc):
        cpp="%s.cpp"%file
        lib = _get_dll_name(file)
        return self.compile_file(cpp, lib, gcc, True)

    def compile_file(self, filename, lib, gcc="", wipe=False):
        parms = [gcc, "-fPIC", "-lstdc++", "-shared", "-o", lib, filename]
        (ret, output) = self.run_capture(parms)
        if ret == 0:
            if wipe:
                os.remove(filename)
            return lib
        else:            
            raise EmbedCompileError(filename, ret, parms[0], parms, output)
        
    def temp_compile(self, code):
        (fp, filename) = tempfile.mkstemp(".cpp")
        fpo = os.fdopen(fp, "w")
        funcname = "func"
        code.write_func(fpo, funcname)
        fpo.close()
        lib = "%s.%s" % (filename, dllext)
        self.compile_file(filename, lib, code.gcc, True)
        _cleanup.add(lib)
        return lib, funcname

        
if platform.system() == "Windows":
    windows = True
    dllext = "dll"
else:
    windows = False
    dllext = "so"

_EmbedCompile().testcc()
