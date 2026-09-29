---VERTEX---
#version 120
attribute vec3 pos;
attribute vec3 normal;
attribute vec4 color;
uniform mat4 modelview_mat;
uniform mat4 projection_mat;
uniform mat4 normal_mat;
varying vec4 frag_color;
varying vec3 frag_normal;
varying vec3 frag_pos;
void main(void) {
    vec4 pos_view = modelview_mat * vec4(pos, 1.0);
    gl_Position = projection_mat * pos_view;
    frag_pos = pos_view.xyz;
    frag_normal = mat3(normal_mat) * normal;
    frag_color = color;
}
---FRAGMENT---
#version 120
varying vec4 frag_color;
varying vec3 frag_normal;
varying vec3 frag_pos;
uniform vec3 light_pos;
uniform vec3 light_pos2;
uniform vec3 camera_pos;
uniform float Ka;
uniform float light_intensity;
uniform float specular_power;
void main(void) {
    vec3 N = normalize(frag_normal);
    vec3 V = normalize(camera_pos - frag_pos);

    vec3 lighting = Ka * frag_color.rgb;

    // 主光(Phong reflect 高光,同 ReachControl 的 blinnphongv3.glsl;
    // 高光色为固定 0.4 灰 —— RC 的 urdfloader 对每个材质硬编码
    // specular=(0.4,0.4,0.4))
    vec3 L1 = normalize(light_pos - frag_pos);
    float diff1 = max(dot(N, L1), 0.0);
    vec3 R1 = reflect(-L1, N);
    float spec1 = pow(max(dot(V, R1), 0.0), specular_power);
    lighting += light_intensity * (diff1 * frag_color.rgb
              + spec1 * vec3(0.4));

    // 补光(与主光对称,照亮背光面;仿 ReachControl)
    vec3 L2 = normalize(light_pos2 - frag_pos);
    float diff2 = max(dot(N, L2), 0.0);
    vec3 R2 = reflect(-L2, N);
    float spec2 = pow(max(dot(V, R2), 0.0), specular_power);
    lighting += light_intensity * (diff2 * frag_color.rgb
              + spec2 * vec3(0.4));

    gl_FragColor = vec4(clamp(lighting, 0.0, 1.0), frag_color.a);
}
