---VERTEX---
#version 120
attribute vec3 pos;
attribute vec4 color;
uniform mat4 modelview_mat;
uniform mat4 projection_mat;
varying vec4 frag_color;
void main(void) {
    gl_Position = projection_mat * modelview_mat * vec4(pos, 1.0);
    frag_color = color;
}
---FRAGMENT---
#version 120
varying vec4 frag_color;
void main(void) {
    gl_FragColor = frag_color;
}
