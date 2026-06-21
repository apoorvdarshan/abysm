//
//  Shaders.swift
//  Abysm
//
//  GLSL fragment shaders used by the environment. SpriteKit provides
//  `u_time`, `v_tex_coord`, and `u_texture` automatically; any other uniform
//  must be declared in the GLSL and registered as an SKUniform.
//

import SpriteKit

enum Shaders {

    /// Animated underwater caustics — the dancing net of light just below the
    /// surface. Designed for an additive sprite anchored at the surface; the
    /// pattern is brightest at the top (uv.y → 1) and fades with depth.
    static func caustics() -> SKShader {
        let shader = SKShader(source: causticsSource)
        shader.uniforms = [
            SKUniform(name: "u_intensity", float: 0.85),
            SKUniform(name: "u_scale_x", float: 6.0),
            SKUniform(name: "u_scale_y", float: 11.0),
            SKUniform(name: "u_speed", float: 0.60)
        ]
        return shader
    }

    // NOTE: custom uniforms (u_intensity, u_scale_x, …) are auto-declared by
    // SpriteKit from the SKUniform array. Do NOT redeclare them with `uniform`
    // here — the Metal backend treats `uniform` as a reserved template type and
    // the shader fails to compile (silently falling back to the base texture).
    private static let causticsSource = """
    void main() {
        vec2 uv = v_tex_coord;
        vec2 p = uv * vec2(u_scale_x, u_scale_y);
        float t = u_time * u_speed;

        // Slowly drift the whole field so it never looks static.
        vec2 q = p + vec2(t * 0.15, t * 0.10);

        // Three drifting wave fields. We keep only the bright crest of each
        // (pow of the positive part) so each contributes a THIN band, then take
        // their union. The background stays genuinely dark, so the turquoise
        // water shows through the gaps instead of washing to white.
        float w1 = sin(q.x * 2.7 + sin(q.y * 1.9 + t));
        float w2 = sin(q.y * 2.3 + sin(q.x * 2.9 - t * 1.1));
        float w3 = sin((q.x + q.y) * 1.7 - t * 0.6);

        float c1 = pow(max(0.0, w1), 12.0);
        float c2 = pow(max(0.0, w2), 12.0);
        float c3 = pow(max(0.0, w3), 12.0);
        float caustic = max(c1, max(c2, c3));

        // Strong near the surface (top of the sprite), fading downward.
        float fade = smoothstep(0.0, 0.55, uv.y);

        float intensity = caustic * fade * u_intensity;
        vec3 lightColor = vec3(0.80, 1.0, 0.95);
        gl_FragColor = vec4(lightColor * intensity, 1.0);
    }
    """
}
