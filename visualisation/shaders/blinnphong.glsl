---VERTEX SHADER---
#ifdef GL_ES
    precision highp float;
#endif

/* 顶点属性 */
attribute vec3  v_pos;
attribute vec3  v_normal;
attribute vec4  v_color;

/* Kivy 自动设置:modelview_mat 由 PushMatrix 栈提供 */
uniform mat4 modelview_mat;
uniform mat4 projection_mat;
uniform mat4 normal_mat;

varying vec4 frag_color;
varying vec3 frag_normal;
varying vec3 frag_pos;

void main (void) {
    vec4 pos = modelview_mat * vec4(v_pos, 1.0);
    frag_pos = pos.xyz;
    frag_normal = normalize(vec3(normal_mat * vec4(v_normal, 0.0)));
    frag_color = v_color;
    gl_Position = projection_mat * pos;
}

---FRAGMENT SHADER---
#ifdef GL_ES
    precision highp float;
#endif

varying vec4 frag_color;
varying vec3 frag_normal;
varying vec3 frag_pos;

/* 世界系光源/相机位置(由程序传入) */
uniform vec3 light_pos;
uniform vec3 camera_pos;
uniform vec3 Ka;              /* 环境光反射率 */
uniform float light_intensity;
uniform float specular_power;

void main (void) {
    vec3 N = normalize(frag_normal);
    vec3 L = normalize(light_pos - frag_pos);
    vec3 V = normalize(camera_pos - frag_pos);
    vec3 H = normalize(L + V);          /* Blinn-Phong 半程向量 */

    vec3 ambient = Ka * frag_color.rgb * light_intensity;
    float diff = max(dot(N, L), 0.0);
    vec3 diffuse = frag_color.rgb * diff * light_intensity;
    float spec = pow(max(dot(N, H), 0.0), specular_power);
    vec3 specular = vec3(0.4) * spec * light_intensity;

    vec3 color = ambient + diffuse + specular;
    gl_FragColor = vec4(color, frag_color.a);
}
