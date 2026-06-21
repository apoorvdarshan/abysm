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
            SKUniform(name: "u_intensity", float: 0.55),
            SKUniform(name: "u_scale_x", float: 10.0),
            SKUniform(name: "u_scale_y", float: 17.0),
            SKUniform(name: "u_speed", float: 0.55)
        ]
        return shader
    }

    // NOTE: custom uniforms (u_intensity, u_scale_x, …) are auto-declared by
    // SpriteKit from the SKUniform array. Do NOT redeclare them with `uniform`
    // here — the Metal backend treats `uniform` as a reserved template type and
    // the shader fails to compile (silently falling back to the base texture).
    private static let causticsSource = """
    // Sharpen a wave crest into a thin bright band == max(0,w)^12, computed with
    // multiplies instead of pow() (pow with a non-constant base is costly on
    // mobile GPUs and this runs per-pixel over a full-screen additive sprite).
    float ridge(float w) {
        float a = max(0.0, w);
        float a2 = a * a;
        float a4 = a2 * a2;
        return a4 * a4 * a4;
    }

    // One caustic octave: three drifting wave fields, keeping only the bright
    // crest of each (ridge == max(0,w)^12) so each is a THIN band, unioned with
    // max(). The background stays dark, so the water shows through the gaps.
    float causticLayer(vec2 uv, float t, vec2 scl) {
        vec2 q = uv * scl + vec2(t * 0.15, t * 0.10);
        float w1 = sin(q.x * 2.7 + sin(q.y * 1.9 + t));
        float w2 = sin(q.y * 2.3 + sin(q.x * 2.9 - t * 1.1));
        float w3 = sin((q.x + q.y) * 1.7 - t * 0.6);
        return max(ridge(w1), max(ridge(w2), ridge(w3)));
    }

    void main() {
        vec2 uv = v_tex_coord;
        float t = u_time * u_speed;

        // Two octaves: a finer base net plus a coarser, slower-drifting layer,
        // giving a delicate dancing web instead of a few bold stripes.
        float c = causticLayer(uv, t, vec2(u_scale_x, u_scale_y));
        c += 0.55 * causticLayer(uv, t * 1.35, vec2(u_scale_x * 0.55, u_scale_y * 0.55));

        // Strong near the surface (top of the sprite), fading downward.
        float fade = smoothstep(0.0, 0.55, uv.y);

        float intensity = c * fade * u_intensity;
        vec3 lightColor = vec3(0.80, 1.0, 0.95);
        gl_FragColor = vec4(lightColor * intensity, 1.0);
    }
    """
}
