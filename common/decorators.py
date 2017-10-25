import os
import time
import inspect

def stats_wrapper(fn):
    if not hasattr(stats_report, 'stats'):
        stats_report.stats = dict()
    frame = inspect.currentframe().f_back
    f_locals = frame.f_locals
    
    filename = os.path.basename(frame.f_code.co_filename)
    clsname = f_locals['__qualname__'] if '__qualname__' in f_locals else ''
    linenum = frame.f_lineno
    fnname = fn.__name__
    key = '%s%s (%s:%d)' % (clsname + ('.' if clsname else ''), fnname, filename, linenum)
    stats = stats_report.stats
    stats[key] = {
        'filename': filename,
        'clsname': clsname,
        'linenum': linenum,
        'fnname': fnname,
        'count': 0,
        'total time': 0,
        'average time': 0,
    }
    def wrapped(*args, **kwargs):
        time_beg = time.time()
        ret = fn(*args, **kwargs)
        time_end = time.time()
        time_delta = time_end - time_beg
        d = stats[key]
        d['count'] += 1
        d['total time'] += time_delta
        d['average time'] = d['total time'] / d['count']
        return ret
    return wrapped

def stats_report():
    stats = stats_report.stats if hasattr(stats_report, 'stats') else dict()
    l = max(len(k) for k in stats)
    def fmt(s): return s + ' '*(l-len(s))
    print()
    print('Call Statistics Report')
    
    cols = [
        ('class','clsname','%s'),
        ('func','fnname','%s'),
        ('file','filename','%s'),
        ('line','linenum','% 10d'),
        ('count','count','% 8d'),
        ('total (sec)','total time', '% 10.4f'),
        ('avg (sec)','average time', '% 10.6f'),
    ]
    data = [stats[k] for k in sorted(stats)]
    data = [[h] + [f % row[c] for row in data] for (h,c,f) in cols]
    colwidths = [max(len(d) for d in col) for col in data]
    totwidth = sum(colwidths) + len(colwidths)-1
    
    def printrow(i_row):
        row = [col[i_row] for col in data]
        print(' '.join(d+' '*(w-len(d)) for d,w in zip(row,colwidths)))
    
    printrow(0)
    print('-'*totwidth)
    for i in range(1, len(data[0])):
        printrow(i)


def timed_call(label):
    def wrapper(fn):
        def wrapped(*args, **kwargs):
            time_beg = time.time()
            ret = fn(*args, **kwargs)
            time_end = time.time()
            time_delta = time_end - time_beg
            print('Timing: %0.4fs, %s' % (time_delta, label))
            return ret
        return wrapped
    return wrapper
