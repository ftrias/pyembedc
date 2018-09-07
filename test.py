import unittest
import inspect
import ctypes

import pyembedc as c

globalvariable = 5

class TestSequenceFunctions(unittest.TestCase):
    
    def setUp(self):
        pass

    def test_embed_return(self):
        r = c.inline_c_precompile("""
                return  15;
                """)
        self.assertEqual(r, 15)
        
        r = c.inline_c_precompile("""
                return  -10;
                """)
        self.assertEqual(r, -10)

    def test_embed_simple(self):
        r = c.C("""
                return  19;
                """)
        self.assertEqual(r, 19)

    def test_embed_return_str(self):
        r = c.inline_c_precompile("""
                RETURN string (char *)"xyz";
                """)
        self.assertEqual(r, "xyz")
        
        r = c.inline_c_precompile("""
                RETURN ustring (wchar_t *)L"abc";
                """)
        self.assertEqual(r, "abc")
        
    def test_embed_integers(self):
        test1=9
        global test2
        test2=11
        r = c.inline_c_precompile("""
            IMPORT int test1
            IMPORT int &test2
            if (test1 != 9) {
                return 1;
            }
            if (test2 != 11) {
                return 2;
            }
            test2 = 99;
            return 0;
            """)
        self.assertEqual(r, 0)
        self.assertEqual(test2, 99)

    def test_embed_local(self):
        test1=9
        a=[2,4,6]
        b=(9,10,11)
        r = c.inline_c_precompile("""
            IMPORT int &test1
            IMPORT int[] a
            IMPORT int[] b
            if (test1 != 9) {
                return 1;
            }
            test1 = 99;
            a[0] = 10;
            b[0]=50;
            return 0;
            """)
        self.assertEqual(r, 0)
        self.assertEqual(test1, 99)
        self.assertEqual(a[0], 10)
        
    def test_embed_tuple(self):
        global arrayb
        arrayb=(9,10,11)
        r = c.inline_c_precompile("""
            IMPORT int[] arrayb
            arrayb[0]=15;
            """)
        self.assertEqual(arrayb[0], 9)
        
    def test_embed_doubles(self):
        test1=9.9
        global test2
        test2=11.1
        r = c.inline_c_precompile("""
            IMPORT double test1
            IMPORT double &test2
            if (test1 != 9.9) {
                return 1;
            }
            if (test2 != 11.1) {
                return 2;
            }
            test2 = 99.9;
            return 0;
            """)
        self.assertEqual(r, 0)
        self.assertEqual(test2, 99.9)

    def test_embed_array(self):
        global test1
        test1=[5,10,15]
        test2=[]
        r = c.inline_c_precompile("""
            IMPORT int[] test1
            IMPORT int[] test2
            if (test1[0] != 5) return 1;
            if (test1[1] != 10) return 2;
            if (test1[2] != 15) return 3;
            test1[0]=4;
            test1[1]=6;
            test1[2]=8;
            return 0;
            """)
        self.assertEqual(r, 0)
        self.assertEqual(test1[0], 4)
        self.assertEqual(test1[1], 6)
        self.assertEqual(test1[2], 8)

    def test_embed_string(self):
        strtest1="x"
        global strtest2
        strtest2="one two"
        strtest3="two three"
        r = c.inline_c_precompile("""
            GLOBAL char *savstr;
            IMPORT string strtest1;
            IMPORT string &strtest2;
            IMPORT string &strtest3;
            if (strcmp(strtest1, "x")!=0) return 1;            
            if (strcmp(strtest2, "one two")!=0) return 2;
            strtest1 = "junk";
            savstr=strdup("five six");
            strtest2 = savstr;
            strtest3 = "four five";
            return 0;
            POST free(savstr);
            """)
        self.assertEqual(r, 0)
        self.assertEqual(strtest1, "x")
        self.assertEqual(strtest2, "five six")
        self.assertEqual(strtest3, "four five")

    def test_embed_unicode_string(self):
        global strtest9
        strtest9="one two"
        r = c.inline_c_precompile("""
            IMPORT ustring &strtest9;
            strtest9 = (wchar_t*)L"nine ten";
            """)
        self.assertEqual(strtest9, "nine ten")

    def sub_test_ctypes_error(self):
        x=ctypes.c_int   # we should really define an instance; this defines a type
        c.inline_c_precompile("""
            IMPORT int x
            x=10;
            """)
            
    def test_embed_ctypes(self):
        x=ctypes.c_int(5)
        y=ctypes.c_int(7)
        c.inline_c_precompile("""
            IMPORT int &x
            IMPORT int y
            x=y;
            """)
        self.assertEqual(x, 7)
        self.assertRaises(c.EmbedParseError, self.sub_test_ctypes_error)
        
    def sub_test_parse_error(self):
        x="xyz"
        c.inline_c_precompile("""
            IMPORT int x
            x=10;
            """)
    
    def test_embed_parse_error(self):
        self.assertRaises(c.EmbedParseError, self.sub_test_parse_error)
        
    def test_embed_ex_embed(self):
        fxlib = c.embed_c("""
            int val() { return %d; }
            """ % 8)
        r = fxlib.val()
        self.assertEqual(r, 8)

    def test_embed_directives(self):
        r = c.inline_c_precompile("""
            GLOBAL int globalx;
            CC --version
            #include <math.h>
            return 4;
            POST globalx=3;
            """)
        self.assertEqual(r, 4)
        
        r = c.inline_c_precompile("""
            return globalx;
            """)
        self.assertEqual(r, 3)

        r = c.inline_c_precompile("""
            IMPORT int globalvariable;
            return globalvariable;
            """)
        self.assertEqual(r, 5)

        r = c.inline_c("""
            #include <math.h>
            return pow(8,2);
            """)
        self.assertEqual(r, 64)

    def test_embed_return_double(self):
        r = c.inline_c_precompile("""
            RETURN double 4.5;
            """)
        self.assertEqual(r, 4.5)

    def sub_test_embed_failcc(self):
        c.embed_c("""
            xxxint val() { return 1; }
            """)
        
    def test_embed_failcc(self):
        self.assertRaises(c.EmbedCompileError, self.sub_test_embed_failcc)

    def test_embed_xgcc1(self):
        try:
            r = c._EmbedCompile().testcc()
        except:
            r = False
        self.assertEqual(r, True)
            
    def test_embed_xgcc2(self):
        try:
            ret = 1
            ret = c._EmbedCompile().testgcc("cat", "no-file-here")
            r = True
        except:
            r = False
        self.assertNotEqual(ret, 0)    
        self.assertEqual(r, False)
        
    def test_embed_xgcc3(self):
        try:
            c._EmbedCompile().testgcc("xxgcc")
            ok = 0
        except:
            ok = 1
        self.assertEqual(ok, 1)

    def test_embed_ex_inline(self):
        r = c.inline_c("""
                return %d;
            """ % 4)
        self.assertEqual(r, 4)
    
    def test_embed_ex(self):
        fxlib = c.embed_c_precompile("""
            int multval(int x1, int y1) {
                return x1*y1;
            }
            
            char* myval2(char *x) {
                return (char*)"Ho ho ho";
            }

            wchar_t* myval3(wchar_t *x) {
                return (wchar_t*)L"Ho ho ho";
            }
            
            int alterint(int &x) {
                x = 7;
                return 3;
            }
            
            int chgval(int *x) {
                x[0] = 10;
                x[1] = 15;
                x[2] = 20;
                return 10;
            }
            """)
        self.assertEqual(fxlib.multval(5,6), 30)
        
        fxlib.myval2.restype = ctypes.c_char_p
        self.assertEqual(fxlib.myval2("test nothing").decode('ascii'), "Ho ho ho")
        fxlib.myval3.restype = ctypes.c_wchar_p
        self.assertEqual(fxlib.myval3("test nothing"), "Ho ho ho")

        cy=ctypes.c_int(5)
        fxlib.alterint(ctypes.byref(cy))
        self.assertEqual(cy.value, 7)

        cx=(ctypes.c_int * 3)()
        fxlib.chgval(cx)
        self.assertEqual(cx[0], 10)
        self.assertEqual(cx[1], 15)
        self.assertEqual(cx[2], 20)

    def test_embed_simple_type_switch(self):
        vs = 1
        r = c.inline_c_precompile("""
            IMPORT ustring &vs
            vs = (wchar_t*)L"test";
            """)
        self.assertEqual(vs, "test")
        
    def test_embed_inline_importall(self):
        v = 1
        r = c.inline_c("""
            IMPORTALL
            IMPORT int v
            if (v==1) return 1;
            return 0;
            """)
        self.assertEqual(r, 1)
        
        r = c.inline_c("""
            if (v==1) return 1;
            return 0;
            """)
        self.assertEqual(r, 1)

        v = [5,6,7]
        r = c.inline_c("""
            v[1] = v[2];
            return v[1];
            """)
        self.assertEqual(r, 7)
        self.assertEqual(v[1], 7)

    def test_embed_function(self):
        mynum = 0.0
        r = c.inline_c_precompile("""
            DEF double mult double double
            IMPORT double &mynum
            mynum = mult(3.1, 2);
            """)
        self.assertEqual(mynum, 6.2)
        
        # This test leaks memory, presumaby the string returned by "altstring"
        #mystr = "first"
        #r = c.inline_c_precompile("""
        #    GLOBAL const char *savstr2;
        #    DEF string altstring string
        #    IMPORT string &mystr
        #    savstr2 = altstring(mystr);
        #    mystr = savstr2;
        #    POST free(savstr2);
        #    """)
        #self.assertEqual(mystr, "123")
        
    def test_embed_savelocals_errors(self):
        frame = inspect.currentframe()
        r = c._savelocals(inspect.currentframe())
        self.assertEqual(r, True)
        self.assertRaises(c.SaveLocalsError, c._savelocals, 1)
        self.assertRaises(c.SaveLocalsError, c._savelocals, None)
        self.assertRaises(c.SaveLocalsError, c._savelocals, frame, 1)
        self.assertRaises(c.SaveLocalsError, c._savelocals, frame, 2)
        self.assertRaises(c.SaveLocalsError, c._savelocals, frame, 3)
        self.assertRaises(c.SaveLocalsError, c._savelocals, frame, 4)
        self.assertRaises(c.SaveLocalsError, c._savelocals, frame, 5)

def mult(x, y):
    return x * y
    
def altstring(s):
    return "123"
    
if __name__ == '__main__':
    unittest.main()
