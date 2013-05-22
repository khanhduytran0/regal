#!/usr/bin/python

import os.path
import re
import sys

from inspect import isfunction

from ApiUtil import validVersion
from ApiUtil import maxLength

def pathBasename(path):

  # When gmake on Cygwin is used with Cygwin python, the path contains '\'
  return os.path.basename(os.sep.join(path.split('\\')))

def autoGeneratedCode(argv):

  argIsFile = False
  message = pathBasename(argv[0])
  for i in range(1, len(argv)):
    if argIsFile:
      message += ' ' + pathBasename(argv[i])
      argIsFile = False
    else:
      message += ' ' + argv[i]
      if argv[i] in ['-o', '--output', '--header', '--source']:
        argIsFile = True

  return message

autoGeneratedMessage = '''/* NOTE: Do not edit this file, it is generated by a script:
   %s
*/
''' % autoGeneratedCode(sys.argv)

# Generate macro condition code and update currCondition with newCondition.

def conditionCode(currCondition, newCondition):

  code = ''
  newCondition = newCondition.strip()

  # End current condition segment.

  if len(currCondition) and not currCondition == newCondition:
    code += '#endif\n'

  # Start a new condition segment.

  if not len(currCondition) or not currCondition == newCondition:
    currCondition = newCondition
    if len(currCondition):
      code += '%s\n' % currCondition

  # Return code and the updated currCondition.

  return code, currCondition

# Generate include code.

def includeCode(header):

  if header.find('<') is -1 and header.find('"') is -1:
    return '#include <%s>' % header

  return '#include %s' % header

# Generate header includes code.

def headerCode(headers):

  code = ''
  for header in headers:
    if len(header.strip()):
      code += '%s\n' % includeCode(header.strip())
  return code

def enumerantCode(enumerant, width = 0):

  line = '%s' % enumerant.name.ljust(width)
  if isinstance(enumerant.value, int):
    line += ' = %d' % enumerant.value
  elif isinstance(enumerant.value, str) and len(enumerant.value):
    line += ' = %s' % enumerant.value
  return line

def enumerantListCode(enumerants, comments = None):

  lines = []
  size = len(enumerants)
  enumerantWidth = maxLength(enumerants, len) + 1
  commentWidth   = maxLength(comments, len)
  for i in xrange(size):
    enum = enumerants[i]
    if i < size - 1:
      enum += ','
    comment = ''
    if comments is not None and comments[i]:
      comment = ' /* %s */' % (comments[i].ljust(commentWidth))
    lines.append(('%s%s' % (enum.ljust(enumerantWidth), comment)).rstrip())
  return lines

#
# Code generation for C++ inlined enumeration query
#
# Inputs:
#         enumerants  list of enumerants
#         test        filter criteria for enumerants
#         name        name of the inlined function
#         type        input type of the inlined function
#
# Output:
#         C++ code as a multi-line string
#
# Example output:
#
#   inline bool cgiIsTessellationEvaluationProfile(const CGprofile p)
#   {
#     return
#       p==CG_PROFILE_GP5TEP ||
#       p==CG_PROFILE_DS_5_0;
#   }
#

def enumerationQueryCode(enumerants, test, name, type):
  var = 'p'
  if type=='CGtype':
    var = 't'
  ret = []
  ret.append('\ninline bool %s(const %s %s)'%(name,type,var))
  ret.append('{')
  subset = [i for i in enumerants if test(i)];
  if len(subset):
    width = maxLength(subset, lambda i:( len(i.name) ))
    ret.append('  return')
    last = subset.pop()
    for i in subset:
      ret.append('    %s==%s ||'%(var,i.name.ljust(width)))
    ret.append('    %s==%s;'%(var,last.name))
  else:
    ret.append('  return false;')
  ret.append('}')
  return '\n'.join(ret)

# Code generation for parameter name.

def paramNameCode(name, index):

  # Generate a default name of the form args_<index>.
  if name == '':
    return 'arg_%s' % index

  return name

# Code generation for parameters types and names. Uses default name if name is missing.

def paramsCode(parameters, cMode = False):

  if len(parameters) is 0:
    if cMode:
      return 'void'
    else:
      return ''

  code = []
  for i in range(len(parameters)):
    param = parameters[i]

    # A hacky workaround for glut.py function pointer purposes
    if param.type.find('GLUTCALLBACK *')>=0:
      code.append('%s' % (typeSansArrayCode(param.type).replace('GLUTCALLBACK *','GLUTCALLBACK *%s' % (param.name)).strip()))
    elif param.type.find('CDECL *')>=0:
      code.append('%s' % (typeSansArrayCode(param.type).replace('CDECL *','CDECL *%s' % (param.name)).strip()))
    else:
      code.append('%s%s%s' % (typeSansArrayCode(param.type), paramNameCode(param.name, i), typeArrayCode(param.type)))

  return ', '.join(code)

# Code generation for parameters types and names. Uses '' if name is missing.

def paramsDeclCode(parameters, cMode = False):

  if len(parameters) is 0:
    if cMode:
      return 'void'
    else:
      return ''

  code = []
  for param in parameters:
    code.append('%s%s%s' % (typeSansArrayCode(param.type), param.name, typeArrayCode(param.type)))
  return ', '.join(code)

# Code generation for parameters types.

def paramsTypeCode(parameters, cMode = False):

  if len(parameters) is 0:
    if cMode:
      return 'void'
    else:
      return ''

  code = []
  for param in parameters:
    code.append('%s' % param.type.strip())
  return ', '.join(code)

# Code generation for parameters names.

def paramsNameCode(parameters):

  if len(parameters) is 0:
    return ''

  code = []
  for i in range(len(parameters)):
    code.append('%s' % paramNameCode(parameters[i].name, i))
  return ', '.join(code)

# Code generation for parameters types, names, and default values.

def paramsDefaultCode(parameters, cMode = False):

  if len(parameters) is 0:
    if cMode:
      return 'void'
    else:
      return ''

  code = []
  for param in parameters:
    line = '%s%s%s' % (typeSansArrayCode(param.type), param.name, typeArrayCode(param.type))
    if not cMode:
      if isinstance(param.default, int):
        line += ' = %d' % param.default
      elif isinstance(param.default, float):
        line += ' = %f' % param.default
      elif isinstance(param.default, str) and len(param.default):
        line += ' = %s' % param.default
    code.append(line)
  return ', '.join(code)

# Code generation for typedef declaration.

def typedefCode(typedef, version, cMode = False):

  if not validVersion(typedef.version, version):
    return ''

  if len(typedef.function):
    return ('typedef %s(*%s)(%s);\n' %
            (typeCode(typedef.type), typedef.name, paramsTypeCode(typedef.parameters, cMode)))

  return 'typedef %s%s;\n' % (typeCode(typedef.type), typedef.name)

# Code generation for function prototype.

def funcProtoCode(function, version, call = None, cMode = False):

  if not validVersion(function.version, version):
    return ''

  if not call:
    call = ''
  else:
    call += ' '
  return 'typedef %s(%s*PFN%sPROC)(%s);' % (typeCode(function.ret.type), call, function.name.upper(), paramsDeclCode(function.parameters, cMode))

# Code generation for function pointer variable declaration.

def funcVarCode(function, version):

  if not validVersion(function.version, version):
    return ''

  return ('%s(*%s)(%s);\n' %
          (typeCode(function.ret.type), function.name, paramsTypeCode(function.parameters)))

# Code generation for type.

def typeCode(pType):

  # Remove extraneous space.
  rType = pType.strip()

  # Add space after type name if type does not end in * or &.
  if rType[-1] != '*' and rType[-1] != '&':
    rType += ' '

  return rType

# Code generation for non-array and array parts of type.

reArray = re.compile('\[.*\]$')

def typeSansArrayCode(pType):

  rType = reArray.sub('', pType).strip()
  return typeCode(rType)

def typeArrayCode(pType):

  array = ''
  mArray = reArray.search(pType)
  if mArray:
    array = mArray.group().strip()
  return array

#
# CodeGen for pointer lookup by name
#
# [ (name,value), ... ] ( namesVar, valuesVar) valueType valueCast
#
# >>> names = [ 'c', 'b', 'a' ]
# >>> values = [ '_c', '_b', '_a' ]
# >>> print '\n'.join(ApiCodeGen.pointerLookupByNameCode((names,values),("names","values")))
# static const char const *names[4] = {
#   "a",
#   "b",
#   "c",
#   NULL
# };
#
# static const void *values[4] = {
#   (void *) _a,
#   (void *) _b,
#   (void *) _c,
#   NULL
# };

def pointerLookupByNameCode(values, names, valueType = 'void *', valueCast = 'reinterpret_cast<void *>(%s)'):

  # Sort the tuples
  values = sorted(values)

  # Construct arrays for name lookup and corresponding value

  code = []
  code.append( 'const char * const %s[%d] = {' % (names[0], len(values)+1 ) ) # terminating NULL
  for i in values:
    code.append( '  "%s",' % i[0] )
  code.append( '  NULL')
  code.append('};')
  code.append('')

  code.append( 'const void *%s[%d] = {'       % (names[1], len(values)+1 ) ) # terminating NULL
  for i in values:
    code.append( '  ' + valueCast%(i[1]) + ',' )
  code.append( '  NULL')
  code.append('};')
  code.append('')

  return code

#
# CodeGen for:
#
#   'a  b     c\td' -> 'a b c d'
#

def stripAll(exp):
  tmp = exp.strip()
  while True:
    tmp = tmp.replace('  ',' ')
    tmp = tmp.replace('\t\t',' ')
    if tmp==exp:
      return tmp
    exp = tmp

#
# CodeGen for:
#
#   #if FOO
#   a
#   #else /* FOO */
#   b
#   #endif /* FOO */
#

def wrapIf(exp, a, b = None):
  if isinstance(a,list):
    tmp = []
    if exp:
      tmp.append('#if %s'%(exp))
      tmp.extend(a)
      if not b==None:
        tmp.append('#else /* %s*/'%(exp))
        tmp.extend(b)
      tmp.append('#endif /* %s */'%(exp))
    else:
      tmp.extend(a)
    return tmp

  tmp = ''
  if exp:
    tmp += '#if %s\n'%(exp)
    tmp += a
    if not b==None:
      tmp += '#else /* %s*/\n'%(exp)
      tmp += b
    tmp += '#endif /* %s */\n'%(exp)
  else:
    tmp += a

  return tmp

#
# CodeGen for:
#
#   if (exp)
#   {
#     a
#   }
#   else /* exp */
#   {
#     b
#   }
#

def wrapCIf(exp, a, b = None):
  exp = stripAll(exp)
  if isinstance(a,list):
    tmp = []
    if exp:
      tmp.append('if (%s)'%(exp))
      tmp.append('{')
      tmp.extend(indent(a))
      tmp.append('}')
      if not b==None:
        tmp.append('else /* %s*/'%(exp))
        tmp.append('{')
        tmp.extend(indent(b))
        tmp.append('}')
    else:
      tmp.extend(a)
    return tmp

  tmp = ''
  if exp:
    tmp += 'if (%s)\n{\n'%(exp)
    tmp += indent(a)
    tmp += '}\n'
    if not b==None:
      tmp += 'else /* %s*/\n{\n'%(exp)
      tmp += indent(b)
      tmp += '}\n'
  else:
    tmp += a

  return tmp

def indent(code,ind = '  '):
  c = code
  if not isinstance(code,list):
    c = code.split('\n')

  c = [ ('%s%s'%(ind,i)).rstrip() for i in c ]

  if isinstance(code,list):
    return c
  else:
    return '\n'.join(c)

#
# CodeGen for inserting empty lines between
# contiguous sequences of the same category
#

def spaceCategory(code,sep = ''):
  res = []
  if not len(code):
    return code
  category = code[0][0]
  for i in code:
    if category != i[0]:
      res.append((category,''))
      category = i[0]
    res.append(i)
  res.append((category,''))
  return res

#
# CodeGen for wrapping contiguous sequences
# of the same category with #if ... #endif
#

def ifCategory(code,condition = '#if 1'):
  res = []
  if not len(code):
    return code
  category = code[0][0]
  if len(category):
    if isfunction(condition):
      res.append((category,condition(category)))
    else:
      res.append((category,condition))
  for i in code:
    if category != i[0]:
      if len(category):
        res.append((category,'#endif'))
      category = i[0]
      if len(category):
        if isfunction(condition):
          res.append((category,condition(category)))
        else:
          res.append((category,condition))
    res.append(i)
  if len(category):
    res.append((category,'#endif'))
  return res

# CodeGen for aligning categories of #defines
#
# #define GL_MULTISAMPLE_BIT_3DFX 0x20000000
# #define GL_MULTISAMPLE_3DFX 0x86b2
# #define GL_SAMPLE_BUFFERS_3DFX 0x86b3
# #define GL_SAMPLES_3DFX 0x86b4
# ->
# #define GL_MULTISAMPLE_BIT_3DFX 0x20000000
# #define GL_MULTISAMPLE_3DFX     0x86b2
# #define GL_SAMPLE_BUFFERS_3DFX  0x86b3
# #define GL_SAMPLES_3DFX         0x86b4
#
def alignDefineCategory(code):

  def lengths(s):
    tmp = []
    for i in s:
      tmp.append(len(i))
    while len(tmp)<4:
      tmp.append(0)
    return tmp

  def maxLength(a,b):
    tmp = []
    for i in xrange(4):
      if a[i]>b[i]:
        tmp.append(a[i])
      else:
        tmp.append(b[i])
    return tmp

  def align(code):
    tmp = []
    maxlen = [ 0,0,0,0 ]
    for i in code:
      l = lengths(i[1].split(' '))
      maxlen = maxLength(maxlen,l)
    if len(code)>1 and maxlen[3]>0:
      maxlen[2] = maxlen[2] + 4
    for i in code:
      s = i[1].split(' ')
      if len(s)>3:
        s[3] = ' '.join(s[3:])
      else:
        s.append('')
      tmp.append((i[0], '#define ' + s[1].ljust(maxlen[1]+1) + s[2].ljust(maxlen[2]+1) + s[3]))
    return tmp

  res = []
  if not len(code):
    return code
  tmp = []
  category = code[0][0]
  for i in code:
    if category != i[0]:
      category = i[0]
      res.extend(align(tmp))
      tmp = []
    tmp.append(i)
  res.extend(align(tmp))
  return res

#
# CodeGen for:
#
#   [ ('c1','foo'), ('c1','bar'), ('c2','hello')] ->
#   [ '/* c1 */', '', 'foo', 'bar', '' ,'/* c2 */', 'hello' ]

def unfoldCategory(code, format = '/* %s */', sortCategory = None, sortWithin = None):

  def flush(category,tmp,res,sortWithin):
    if len(tmp):
      if sortWithin:
        tmp.sort(sortWithin)
      if category and len(category):
        res.append('')
        res.append(format%category)
        res.append('')
      res.extend(tmp)

  if sortCategory:
    code.sort(sortCategory)

  res = []        # output list of strings
  tmp = []        # current list of strings (current category)
  category = None # current category

  for i in code:
    if i[0] != category:
      flush(category,tmp,res,sortWithin)
      category = i[0]
      tmp = []
    tmp.append(i[1])

  flush(category,tmp,res,sortWithin)

  return res

#
# CodeGen for:
#
#   [ 'a', 'b', 'c' ] ->
#   'a\nb\nc\n'

def listToString(code):
  if not len(code):
    return ''
  else:
    return '\n'.join(code) + '\n'

#
# CodeGen for simplifying expression in << sequence
#
#   '(4)' -> '4'
#

def expressionSimplify(code):
  if code.find('<')!=-1 or code.find('?')!=-1:
    return code
  if code[0]=='(' and code[-1]==')':
    return code[1:-1]
  return code
