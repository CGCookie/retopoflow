import bgl

bufLen = bgl.Buffer(bgl.GL_BYTE, 4)
bufLog = bgl.Buffer(bgl.GL_BYTE, 2000)

def shader_compile(shader):
    '''
    logging and error-checking not working :(
    '''
    bgl.glCompileShader(shader)
    bgl.glGetShaderInfoLog(shader, 2000, bufLen, bufLog)
    log = ''.join(chr(v) for v in bufLog.to_list() if v)

def shader_helper(srcVertex, srcFragment):
    
    shaderProg = bgl.glCreateProgram()
    
    shaderVert = bgl.glCreateShader(bgl.GL_VERTEX_SHADER)
    shaderFrag = bgl.glCreateShader(bgl.GL_FRAGMENT_SHADER)
    
    bgl.glShaderSource(shaderVert, srcVertex)
    bgl.glShaderSource(shaderFrag, srcFragment)
    
    shader_compile(shaderVert)
    shader_compile(shaderFrag)
    
    bgl.glAttachShader(shaderProg, shaderVert)
    bgl.glAttachShader(shaderProg, shaderFrag)
    
    bgl.glLinkProgram(shaderProg)
    
    return shaderProg
