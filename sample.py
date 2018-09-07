from embedc import C

def myround(number):
    return round(number, 1)

def test(data):
    datalen = len(data)
    mean = 0.0     // this is a double
    stddev = 0.0   // declare these variables so they can be used by C code
    status="Calculate statistics"
    C("""
        #include <math.h>
        // myround is a python function so we define the return and parameter types
        DEF double myround double
        printf("%s: ", status);
        double sum, sumsq = 0.0;
        for(int i=0;i<datalen; i++) {
            sum += data[i];
        }
        mean = sum / datalen;     // "mean" is a python variable (imports all locals)
        for(int i=0;i<datalen; i++) {
            sumsq += pow((data[i] - mean),2);
        }
        // set the python variable "stddev"
        stddev = myround(sqrt(
            sumsq / (datalen-1)));
        mean = myround(mean);
        status = "Done";   // we can even set python strings
        fflush(stdout);
        """)
    print("Mean = %f" % mean)
    print("Stddev = %f" % stddev)
    print(status)

samples=(10.5,15.1,14.6,12.3,19.8,17.1,6.1)
test(samples)
