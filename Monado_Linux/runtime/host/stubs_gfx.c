// Compatibility hooks the LAS renderer calls (mirror mode, pot tinting,
// pet cursor, save editor, input glue) and for SMAA data. XCDE has none of these game features.  [XCDE]
// [XCDE] LINUX-089: native XCDE camera/aspect support lives in xcde_aspect.c; other legacy hooks remain neutral.
#include <stdbool.h>
#include <stdint.h>

#include "../settings.h"
#include "xcde_aspect.h" // [XCDE] LINUX-089


int rt_reboot_requested(void) { return 0; }
void reboot_test_frame(uint64_t frame) { (void)frame; }
void warp_frame(uint64_t frame) { (void)frame; }
void save_editor_frame(uint64_t frame) { (void)frame; }
const char *game_level_name(void) { return ""; }

bool widescreen_allowed(void) { return xcde_aspect_enabled(); } // [XCDE] LINUX-089/090
void widescreen_backdrop_seen(uint64_t hash) { (void)hash; }
float widescreen_effect_stretch(uint64_t fs_hash) { (void)fs_hash; return 1.0f; }
void widescreen_frame_end(uint64_t frame) { (void)frame; }
void widescreen_present_crop(uint64_t a, double b, float *c, double *d, double *e, double *f, double *g) {
    // full texture, placement left as output_scale() chose it (the real crop is LAS-specific room framing)
    (void)a; (void)b; (void)d; (void)e; (void)f; (void)g;
    c[0] = 0.0f, c[1] = 0.0f, c[2] = 1.0f, c[3] = 1.0f;
}
void widescreen_scene_ubo(const float *u, uint64_t size) { (void)u; (void)size; }
void widescreen_set_factor(float f) { xcde_aspect_set_factor(f); } // [XCDE] LINUX-089

bool mirror_draw(bool composite) { (void)composite; return false; }
bool pets_hide_item_cursor(void) { return false; }
bool pot_glow_active(void) { return false; }
bool pot_level_active(void) { return false; }
bool pot_tint(const float *m, float tint[8], uint64_t mesh) { (void)m; (void)tint; (void)mesh; return false; }
bool pot_instance_gold(const float *m) { (void)m; return false; }
void pot_gold_tint(float tint[8]) { (void)tint; }
void escape_bottle_tint(int kind, const float *ui, uint32_t ui_size, float tint[8]) {
    (void)kind; (void)ui; (void)ui_size; (void)tint;
}

// Link's Awakening feature hooks called by hle/input.c each frame (chamber/digs/pets/warp/qol/mirror/give-item).  [XCDE]
#include "../cpu.h"
char g_window_shot_request[256];
int32_t g_test_lx, g_test_ly, g_stick_lx, g_stick_ly;
uint64_t g_test_stick_until, g_test_buttons, g_test_buttons_until, g_stick_freeze_until;
bool menu_input_captured(void) { return false; }
void warp_game_tick(Cpu *c) { (void)c; }
void give_item_tick(Cpu *c, uint64_t frame) { (void)c; (void)frame; }
void chamber_game_tick(Cpu *c, uint64_t frame) { (void)c; (void)frame; }
void digs_game_tick(Cpu *c, uint64_t frame) { (void)c; (void)frame; }
void qol_tick(void) {}
void pets_game_tick(Cpu *c) { (void)c; }
bool mirror_input(void) { return false; }
uint64_t pets_menu_input(uint64_t b, int32_t st[4]) { (void)st; return b; }
void input_note_rstick(int32_t ry) { (void)ry; }
