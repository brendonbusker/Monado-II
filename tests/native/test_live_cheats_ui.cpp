// [XCDE] LINUX-129: Enemy health controls, positive bounds and live diagnostics.
// [XCDE] LINUX-120: actual ImGui F1 cheat controls without SDL, window or game.
#include "imgui.h"
#include "imgui_internal.h"
#include <cassert>
#include <cstdio>
#include <string>
#include <vector>
#include "../../Monado_Linux/runtime/ui/cheats_controls_linux.h"
#include "../../Monado_Linux/runtime/cheats_options.h"
struct Item { ImGuiID id; std::string label; ImRect box; ImGuiItemFlags flags; };
static std::vector<Item> items;
static Settings state;
static bool crossed_width;
void ImGuiTestEngineHook_ItemAdd(ImGuiContext*, ImGuiID, const ImRect&, const ImGuiLastItemData*) {}
void ImGuiTestEngineHook_ItemInfo(ImGuiContext *ctx, ImGuiID id, const char *label, ImGuiItemStatusFlags) {
    items.push_back(Item{id, label, ctx->LastItemData.Rect, ctx->LastItemData.ItemFlags});
}
void ImGuiTestEngineHook_Log(ImGuiContext*, const char*, ...) {}
const char *ImGuiTestEngine_FindItemDebugLabel(ImGuiContext*, ImGuiID) { return ""; }
static void frame(int width = 640) {
    items.clear(); ImGuiIO &io = ImGui::GetIO(); io.DisplaySize = ImVec2((float)width, 1050); io.DeltaTime = 1.f / 60;
    ImGui::NewFrame(); ImGui::SetNextWindowPos(ImVec2(0,0)); ImGui::SetNextWindowSize(io.DisplaySize);
    ImGui::Begin("F1 Cheats", nullptr, ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoMove);
    if (monado_cheat_controls_linux(&state, true)) xcde_cheats_publish(&state);
    crossed_width = ImGui::GetCurrentWindow()->DC.CursorMaxPos.x > ImGui::GetCurrentWindow()->WorkRect.Max.x + 1;
    ImGui::End(); ImGui::Render();
}
static Item named(const char *label) {
    for (const auto &item : items) if (item.label == label) return item;
    assert(false); return Item{};
}
static std::vector<Item> sliders() {
    std::vector<Item> result;
    for (const auto &item : items) if (item.label == "##multiplier") result.push_back(item);
    return result;
}
static void click(ImVec2 pos) {
    auto &io = ImGui::GetIO(); io.AddMousePosEvent(pos.x,pos.y); io.AddMouseButtonEvent(0,true); frame();
    io.AddMouseButtonEvent(0,false); frame();
}
int main() {
    state.cheat_damage_dealt_percent=state.cheat_damage_received_percent=state.cheat_exp_percent=
        state.cheat_ap_percent=state.cheat_sp_percent=state.cheat_gold_percent=state.cheat_movement_speed_percent=state.cheat_enemy_health_percent=100;
    xcde_cheats_publish(&state);
    ImGui::CreateContext(); auto &io=ImGui::GetIO(); io.IniFilename=nullptr;
    io.ConfigFlags|=ImGuiConfigFlags_NavEnableKeyboard; assert(io.Fonts->Build()); GImGui->TestEngineHookItems=true;
    frame(); frame(); assert(sliders().size()==8);
    for(const auto &item:sliders())assert(item.flags & ImGuiItemFlags_Disabled);
    click(named("Movement speed").box.GetCenter());
    assert(state.cheat_movement_speed && xcde_cheats_snapshot().enabled[XCDE_CHEAT_MOVEMENT_SPEED]);
    assert(!(sliders()[7].flags & ImGuiItemFlags_Disabled));
    for(int i=0;i<7;i++)assert(sliders()[i].flags & ImGuiItemFlags_Disabled);
    auto slider=sliders()[7]; click(ImVec2(slider.box.Max.x-1,slider.box.GetCenter().y));
    assert(state.cheat_movement_speed_percent==2000);
    XcdeCheats maximum=xcde_cheats_snapshot(); assert(xcde_cheats_effective_percent(&maximum,XCDE_CHEAT_MOVEMENT_SPEED)==2000);
    slider=sliders()[7]; click(ImVec2(slider.box.Min.x+1,slider.box.GetCenter().y));
    assert(state.cheat_movement_speed_percent==0);
    ImGui::ActivateItemByID(sliders()[7].id); frame();
    io.AddKeyEvent(ImGuiMod_Ctrl,true); io.AddKeyEvent(ImGuiKey_RightArrow,true); frame();
    io.AddKeyEvent(ImGuiKey_RightArrow,false); io.AddKeyEvent(ImGuiMod_Ctrl,false); frame();
    assert(state.cheat_movement_speed_percent==1 && xcde_cheats_snapshot().percent[6]==1);
    ImGui::ActivateItemByID(sliders()[7].id); frame();
    click(named("No fall damage").box.GetCenter()); assert(xcde_cheats_snapshot().no_fall_damage);
    click(named("Movement speed").box.GetCenter());
    XcdeCheats disabled=xcde_cheats_snapshot(); assert(!disabled.enabled[6] && disabled.percent[6]==1);
    assert(xcde_cheats_effective_percent(&disabled,XCDE_CHEAT_MOVEMENT_SPEED)==100);
    click(named("Enemy health").box.GetCenter()); assert(state.cheat_enemy_health);
    slider=sliders()[2]; click(ImVec2(slider.box.Max.x-1,slider.box.GetCenter().y));
    assert(state.cheat_enemy_health_percent==2000 && xcde_cheats_enemy_health_percent()==2000);
    slider=sliders()[2]; click(ImVec2(slider.box.Min.x+1,slider.box.GetCenter().y));
    assert(state.cheat_enemy_health_percent==10 && xcde_cheats_enemy_health_percent()==10);
    ImGui::ActivateItemByID(sliders()[2].id); frame();
    io.AddKeyEvent(ImGuiMod_Ctrl,true); io.AddKeyEvent(ImGuiKey_RightArrow,true); frame();
    io.AddKeyEvent(ImGuiKey_RightArrow,false); io.AddKeyEvent(ImGuiMod_Ctrl,false); frame();
    assert(state.cheat_enemy_health_percent==11 && xcde_cheats_enemy_health_percent()==11);
    ImGui::ActivateItemByID(sliders()[2].id); frame();
    click(named("Enemy health").box.GetCenter()); assert(!state.cheat_enemy_health && xcde_cheats_enemy_health_percent()==100);
    frame(260); assert(!crossed_width); assert(sliders().size()==8);
    ImGui::DestroyContext(); puts("F1 cheats UI: real toggles, eight sliders, live publication, range/1-percent steps and narrow layout PASS");
}
