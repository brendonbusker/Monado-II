// [XCDE] LINUX-129: Enemy health controls, positive bounds and live diagnostics.
// [XCDE] LINUX-120: actual F1 controls, independently testable without a GPU.
#pragma once
#include "imgui.h"
#include <algorithm>
#include "../settings.h"

static inline bool monado_cheat_controls_linux(Settings *s, bool english) {
    bool changed = false;
    ImGui::TextWrapped("%s", english
        ? "Changes apply during play. Save remembers them for the next launch."
        : "Los cambios se aplican durante la partida. Guardar los recuerda al reiniciar.");
    ImGui::TextWrapped("%s", english ? "Enemy health: 0.1x to 20x. Other multipliers: 0x to 20x. Steps: 0.01x (1%); 1x is unchanged."
        : "Vida enemiga: de 0.1x a 20x. Otros: de 0x a 20x. Pasos: 0.01x (1%); 1x no cambia la cantidad.");
    bool *enabled[] = {&s->cheat_damage_dealt, &s->cheat_damage_received, &s->cheat_exp,
                       &s->cheat_ap, &s->cheat_sp, &s->cheat_gold, &s->cheat_movement_speed, &s->cheat_enemy_health};
    int *percent[] = {&s->cheat_damage_dealt_percent, &s->cheat_damage_received_percent, &s->cheat_exp_percent,
                     &s->cheat_ap_percent, &s->cheat_sp_percent, &s->cheat_gold_percent, &s->cheat_movement_speed_percent, &s->cheat_enemy_health_percent};
    const char *labels[] = {english ? "Party damage dealt" : "Daño causado por el grupo",
        english ? "Party damage received" : "Daño recibido por el grupo", english ? "EXP gained" : "EXP obtenida",
        english ? "AP gained" : "AP obtenidos", english ? "SP gained" : "SP obtenidos",
        english ? "Gold gained" : "Dinero obtenido", english ? "Movement speed" : "Velocidad de movimiento",
        english ? "Enemy health" : "Vida de los enemigos"};
    // Keep persisted/native indexes stable while grouping Enemy health with Combat.
    const int order[] = {0, 1, 7, 2, 3, 4, 5, 6};
    for (int i : order) {
        if (i == 0) ImGui::SeparatorText(english ? "Combat" : "Combate");
        if (i == 2) ImGui::SeparatorText(english ? "Rewards" : "Recompensas");
        if (i == 6) ImGui::SeparatorText(english ? "Exploration" : "Exploración");
        ImGui::PushID(i);
        changed |= ImGui::Checkbox(labels[i], enabled[i]);
        if (i == 7) ImGui::SetItemTooltip("%s", english
            ? "Live changes preserve the current HP percentage. Small health bars retain a safety minimum for scripted phases."
            : "Los cambios conservan el porcentaje de vida actual. Las barras pequeñas mantienen un mínimo de seguridad para las fases con guion.");
        ImGui::BeginDisabled(!*enabled[i]);
        float amount_width = ImGui::CalcTextSize("20.00x").x;
        ImGui::SetNextItemWidth(std::max(40.f, std::min(360.f, ImGui::GetContentRegionAvail().x - amount_width - ImGui::GetStyle().ItemInnerSpacing.x)));
        changed |= ImGui::SliderInt("##multiplier", percent[i], i == 7 ? 10 : 0, 2000, "%d%%", ImGuiSliderFlags_AlwaysClamp);
        ImGui::SetItemTooltip("%s", english ? "Ctrl-click to enter a percentage. Ctrl+arrow adjusts 1%."
            : "Ctrl+clic para escribir un porcentaje. Ctrl+flecha ajusta 1%.");
        ImGui::SameLine(); ImGui::Text("%.2fx", *percent[i] / 100.0);
        ImGui::EndDisabled(); ImGui::PopID();
    }
    changed |= ImGui::Checkbox(english ? "No fall damage" : "Sin daño por caídas", &s->cheat_no_fall_damage);
    ImGui::TextWrapped("%s", english ? "EXP, AP, SP and gold already earned remain in your save after disabling cheats."
        : "La EXP, AP, SP y el dinero ganados permanecen en la partida al desactivar los trucos.");
    return changed;
}
