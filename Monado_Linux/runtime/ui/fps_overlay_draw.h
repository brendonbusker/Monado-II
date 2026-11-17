// [XCDE] LINUX-094/124: authored output-space FPS display, independent of game HUD.
#pragma once
#include "imgui.h"
#include <algorithm>
#include <float.h>
#include <math.h>
#include <stdio.h>

namespace fps_overlay_detail {
enum Mode { Off, Number, Compact, Detailed };
struct Layout {
    bool visible = false;
    float font_size = 0;
    ImVec2 minimum{}, maximum{}, text_position{};
    // Semantic readout retained for diagnostics and authored layout fixtures.
    char text[192]{};
};

// Rendered game frames and accepted output submissions are separate clocks.
// In particular, a driver output total does not identify generated-only frames.
struct Rates {
    bool game_ready = false;
    double game = 0;
    bool generation = false, external = false, output_ready = false;
    bool external_measured = false;
    double output = 0;
    bool generated_ready = false;
    double generated = 0;
};
inline bool valid_rate(bool ready, double value) {
    return ready && isfinite(value) && value >= 0 && value <= 1000000000.;
}
inline void rate_text(char *text, size_t capacity, bool ready, double rate) {
    if (valid_rate(ready, rate)) snprintf(text, capacity, "%.0f", rate);
    else snprintf(text, capacity, "--");
}
inline float text_width(ImFont *font, float size, const char *text) {
    return font->CalcTextSizeA(size, FLT_MAX, 0, text).x;
}
inline void text(ImDrawList *list, ImFont *font, float size, ImVec2 pos,
                 ImU32 color, const char *value, float scale, bool shadow = false) {
    if (shadow) list->AddText(font, size, ImVec2(pos.x + scale, pos.y + scale),
                             IM_COL32(6, 12, 16, 190), value);
    list->AddText(font, size, pos, color, value);
}

// Fixed-size atlas fonts scale with the output, requiring no per-frame texture
// rebuild, interactive window or guest-HUD modification. All modes share the
// existing sampling path and are drawn after frame generation.
inline Layout draw(int mode, const Rates &rates, float width, float height,
                   ImFont *numbers = nullptr, ImFont *labels = nullptr) {
    Layout result;
    if (mode <= Off || mode > Detailed || !isfinite(width) || !isfinite(height) || width < 4 || height < 4) return result;
    if (!numbers) numbers = ImGui::GetFont();
    if (!labels) labels = ImGui::GetFont();
    char game[24], output[24], generated[24];
    rate_text(game, sizeof game, rates.game_ready, rates.game);
    rate_text(output, sizeof output, rates.output_ready && (!rates.external || rates.external_measured), rates.output);
    bool generated_valid = !rates.external && valid_rate(rates.generated_ready, rates.generated) &&
                           valid_rate(rates.output_ready, rates.output) && rates.generated <= rates.output;
    rate_text(generated, sizeof generated, generated_valid, rates.generated);
    if (mode == Number) snprintf(result.text, sizeof result.text, "%s", game);
    else if (!rates.generation) snprintf(result.text, sizeof result.text, "%s FPS", game);
    else if (rates.external && rates.external_measured)
        snprintf(result.text, sizeof result.text, "Game %s FPS\nOutput %s FPS (driver submitted)\nGenerated unavailable", game, output);
    else if (rates.external)
        snprintf(result.text, sizeof result.text, "Game %s FPS\nOutput external (unavailable)", game);
    else snprintf(result.text, sizeof result.text, "Game %s FPS\nOutput %s FPS (submitted)\nGenerated %s FPS", game, output, generated);

    float unit = std::max(0.8f, std::min(2.0f, height / 1080.0f));
    float number_size = (mode == Detailed ? 30.0f : 36.0f) * unit;
    float label_size = 16.0f * unit, tiny_size = 15.0f * unit;
    float pad = 12.0f * unit, line_height = 42.0f * unit;
    float margin = std::min(12.0f * unit, std::min(width, height) * 0.1f);
    float number_width = std::max(text_width(numbers, number_size, "0000"), text_width(numbers, number_size, game));
    if (mode == Detailed) {
        number_width = std::max(number_width, text_width(numbers, number_size, output));
        if (!rates.external) number_width = std::max(number_width, text_width(numbers, number_size, generated));
    }
    const char *qualifier = !rates.generation ? "Output - submitted frames" : !rates.external ? "FSR - submitted frames" :
                            rates.external_measured ? "NVIDIA - driver submitted" : "NVIDIA - output unavailable";
    char detail[96];
    snprintf(detail, sizeof detail, "OUT %s  |  GEN %s", output, rates.external ? "n/a" : generated);
    float panel_w, panel_h;
    if (mode == Number) {
        panel_w = text_width(numbers, number_size, game) + unit;
        panel_h = number_size + unit;
    } else if (mode == Compact) {
        panel_w = std::max(154.0f * unit, number_width + 8.0f * unit + text_width(labels, label_size, "FPS")) + 2 * pad;
        if (rates.generation) panel_w = std::max(panel_w,
            std::max(text_width(labels, label_size, detail), text_width(labels, tiny_size, qualifier)) + 2 * pad);
        panel_h = number_size + 2 * pad + (rates.generation ? 42.0f * unit : 0.0f);
    } else {
        panel_w = std::max(246.0f * unit, 90.0f * unit + number_width + 8.0f * unit + text_width(labels, tiny_size, "FPS")) + 2 * pad;
        panel_w = std::max(panel_w, text_width(labels, tiny_size, qualifier) + 2 * pad);
        panel_h = 3 * line_height + 67.0f * unit;
    }
    float fit = std::min(1.0f, std::min((width - 2 * margin) / panel_w, (height - 2 * margin) / panel_h));
    if (!isfinite(fit) || fit <= 0) return result;
    unit *= fit; number_size *= fit; label_size *= fit; tiny_size *= fit; pad *= fit; line_height *= fit;
    panel_w *= fit; panel_h *= fit; number_width *= fit;
    result.visible = true; result.font_size = number_size;
    result.minimum = ImVec2(margin, margin);
    result.maximum = ImVec2(margin + panel_w, margin + panel_h);
    result.text_position = ImVec2(margin + (mode == Number ? 0 : pad), margin + (mode == Number ? 0 : pad));
    ImDrawList *list = ImGui::GetForegroundDrawList();
    const ImU32 ivory = IM_COL32(248, 242, 222, 255), muted = IM_COL32(221, 228, 222, 255);
    if (mode == Number) {
        text(list, numbers, number_size, result.text_position, ivory, game, unit, true);
        return result; // Deliberately no backing, unit label, border or other metric.
    }
    float bevel = 5.0f * unit;
    ImVec2 corners[] = {{margin+bevel,margin},{margin+panel_w-bevel,margin},{margin+panel_w,margin+bevel},
        {margin+panel_w,margin+panel_h-bevel},{margin+panel_w-bevel,margin+panel_h},
        {margin+bevel,margin+panel_h},{margin,margin+panel_h-bevel},{margin,margin+bevel}};
    list->AddConvexPolyFilled(corners, 8, IM_COL32(31, 51, 57, 218));
    list->AddPolyline(corners, 8, IM_COL32(223, 224, 204, 215), ImDrawFlags_Closed, unit);
    float left = margin + pad, right = margin + panel_w - pad;
    if (mode == Compact) {
        text(list, numbers, number_size, ImVec2(left, margin + pad - unit), ivory, game, unit, true);
        float fps_x = left + number_width + 8 * unit;
        text(list, labels, label_size, ImVec2(fps_x, margin + pad + number_size - label_size - 3 * unit), ivory, "FPS", unit);
        if (rates.generation) {
            float y = margin + pad + number_size + 3 * unit;
            list->AddLine(ImVec2(left,y), ImVec2(right,y), IM_COL32(109,211,213,230), 1.5f*unit);
            text(list, labels, label_size, ImVec2(left,y + 6*unit), ivory, detail, unit);
            text(list, labels, tiny_size, ImVec2(left,y + 25*unit), muted, qualifier, unit);
        }
    } else {
        float y = margin + 10 * unit;
        text(list, labels, label_size, ImVec2(left,y), ivory, "PERFORMANCE", unit);
        y += 22 * unit;
        list->AddLine(ImVec2(left,y), ImVec2(right,y), IM_COL32(109,211,213,230), 1.5f*unit);
        const char *names[] = {"Game", "Output", "Generated"};
        const char *values[] = {game, output, rates.external ? "n/a" : generated};
        for (int i = 0; i < 3; ++i) {
            y += 7 * unit;
            text(list, labels, label_size, ImVec2(left,y + (number_size-label_size)*0.5f), ivory, names[i], unit);
            float suffix = text_width(labels, tiny_size, "FPS"), value_right = right - suffix - 6 * unit;
            const bool unavailable = rates.external && i == 2;
            const char *value = values[i];
            ImFont *font = unavailable ? labels : numbers;
            float size = unavailable ? label_size : number_size;
            text(list, font, size, ImVec2(value_right-text_width(font,size,value),y), ivory, value, unit, !unavailable);
            if (!unavailable) text(list, labels, tiny_size, ImVec2(right-suffix,y+number_size-tiny_size-3*unit), muted, "FPS", unit);
            y += line_height - 7 * unit;
            if (i < 2) list->AddLine(ImVec2(left,y), ImVec2(right,y), IM_COL32(189,204,198,105), unit);
        }
        text(list, labels, tiny_size, ImVec2(left,y + 7*unit), muted, qualifier, unit);
    }
    return result;
}
// Preserve the original authored component fixture API; enabled means compact.
inline Layout draw(bool enabled, const Rates &rates, float width, float height) {
    return draw(enabled ? Compact : Off, rates, width, height);
}
inline Layout draw(bool enabled, bool ready, double fps, float width, float height) {
    Rates rates; rates.game_ready = ready; rates.game = fps;
    return draw(enabled, rates, width, height);
}
}
