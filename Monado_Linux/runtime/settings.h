// User settings (larecomp.ini next to the executable's working directory), edited from the in-game menu.
#pragma once
#include <stdbool.h>

enum { ASPECT_UNLOCKED = 0, ASPECT_ORIGINAL = 1 };
enum { RES_MATCH = 0, /* 1..8 = 1x..8x */ RES_DYNAMIC = 9, RES_Q75 = 10, RES_Q25 = 11, RES_Q50 = 12 };
// (11 was 67% of the display: larecomp.ini "67%" now loads as RES_Q75)
enum { UPSCALE_BILINEAR = 0, UPSCALE_METALFX = 1 /* macOS */, UPSCALE_FSR1 = 2 /* Windows: AMD FSR 1 */,
       UPSCALE_FSR3 = 3 /* [XCDE] AMD FSR 3.1 (temporal) */, UPSCALE_DLSS = 4 /* [XCDE] NVIDIA DLSS (temporal) */ };
// [XCDE] temporal upscalers' quality mode: render size = output / ratio (1, 1.5, 1.7, 2, 3)
enum { UQ_NATIVE = 0, UQ_QUALITY = 1, UQ_BALANCED = 2, UQ_PERFORMANCE = 3, UQ_ULTRA = 4 };
#ifdef __APPLE__
#define UPSCALE_SHARP UPSCALE_METALFX  // each OS's non-bilinear upscaler (the default)
#else
#define UPSCALE_SHARP UPSCALE_FSR1
#endif
enum { AA_OFF = 0, AA_SMAA = 1 };
enum { PROMPTS_AUTO = 0, PROMPTS_NINTENDO = 1, PROMPTS_XBOX = 2, PROMPTS_PLAYSTATION = 3 };
enum { CHAOS_LETTERS_OFF = 0, CHAOS_LETTERS_EXPLORED = 1, CHAOS_LETTERS_MAP = 2 /* explored, all with the Map */ };
// [XCDE] LINUX-014: held menu/arts navigation repeat; not animation or game speed.
enum { MENU_NAV_NORMAL = 0, MENU_NAV_FAST = 1 };
// System language served to the game (runtime/services/am.c GetDesiredLanguage, services/hid_set.c GetLanguageCode):
// the game picks its text language from it, as it would from the Switch's own system setting. LANG_AUTO follows the
// host locale ($LC_ALL / $LC_MESSAGES / $LANG); the rest are the codes of the languages the game has text for.
enum { LANG_AUTO = 0, N_LANGUAGES = 12 };
extern const char *const g_language_codes[N_LANGUAGES];  // what the game is told: "ja", "en-US", "es", ...
extern const char *const g_language_names[N_LANGUAGES];  // for the menu ("Auto", "Japanese", ..., "Spanish")

typedef struct {
    int aspect;          // ASPECT_*: unlocked = fill the window (wider/taller views), original = 16:9 with bars
    bool fullscreen;
    int res_mode;        // RES_MATCH, 1..4 (N x the Switch's 1080p), RES_DYNAMIC, RES_Q75/50/25 (share of the display)
    int upscaler;        // UPSCALE_*: how a lower internal resolution reaches the window (MetalFX: macOS, FSR 1: Windows)
    int antialias;       // AA_*: anti-aliasing of the game image before it is scaled to the window
    float volume;        // master volume, 1 = 100%
    bool reverb;         // room reverb effect
    bool movie_audio;
    bool show_fps;
    int fps;  // [XCDE] frame rate target: 30 (the game's own), 60, 120, 144..., 0 = unlimited (runtime/hle/framepace.c)
    bool dpad_move;      // the d-pad (and arrow keys) move Link like the stick
    bool move_360;       // analog movement in any direction (the game snaps the stick to 8): runtime/hle/qol.c
    bool blur_removal;   // no tilt-shift blur at the top / bottom of the screen
    bool hide_hero_icon; // no Hero Mode icon on the HUD
    bool mirror_mode;    // the world mirrored left to right (Gameplay tab): renderers + runtime/hle/input.c
    int language;        // LANG_AUTO or an index into g_language_codes: the game's text language
    int prompts;         // PROMPTS_*: button glyphs (auto = follow the controller SDL reports): runtime/nvn/texpatch.c
    bool inv_keys;       // randomizer: show every dungeon's keys on the pause menu's Items page
    bool tracker;        // randomizer: check tracker on the pause menu's Map page
    int chaos_letters;   // CHAOS_LETTERS_*: room-shuffle doorway letters on the dungeon map
    bool aspect_asked;   // the start screen's one-time "authentic 16:9 or unlocked?" question was answered
    bool menu_tip_seen;  // the start screen's one-time "how to open the menu" note was shown (first PLAY ever)
    // cheats (runtime/ui/cheats.mm), applied every frame while a save is loaded
    bool cheat_hearts;   // health kept full
    bool cheat_ammo;     // bombs / arrows / magic powder kept full (for the bags Link owns)
    bool cheat_rupees;   // rupees kept at 999
    bool cheat_hookshot; // hookshot latches onto any surface (Gameplay tab; runtime/hle/hookshot.c; seeds made with it: always)
    bool no_buff_drops;  // no Guardian Acorns / Pieces of Power (Gameplay tab; runtime/hle/qol.c; seeds made with it: always)
    // difficulty (runtime/ui/difficulty.mm)
    float diff_damage;   // damage taken multiplier (1 = normal)
    bool diff_ohko;      // any hit kills
    bool diff_hero;      // Hero Mode flag forced on in the loaded save (2x damage, no recovery hearts)
    // cosmetics (runtime/ui/cosmetics.mm; applied live by runtime/nvn/texpatch.c), never part of a seed
    int tunic;           // index into g_tunic_colours (0 = Default: the game's / the seed's own)
    int hearts;          // index into g_heart_colours (0 = Default red)
    char rando_seed[128];  // active randomizer seed (rando/<name>/), empty = vanilla
    bool dof_off;        // [XCDE] T183: skip the game's depth of field (xcde.ini depth_of_field = 0)
    bool vsync;          // [XCDE] FIFO presentation at 30 / 60 fps (xcde.ini vsync = 0/1, default 1)
    bool game_blur;      // [XCDE] the game's own AA / temporal AA / motion blur (lib_nx.ini; xcde.ini game_blur = 0/1)
    int upscale_quality; // [XCDE] UQ_*: FSR 3 / DLSS render size (xcde.ini upscale_quality = native|quality|balanced|performance|ultra)
    bool frame_gen;      // [XCDE] FSR 3 / DLSS frame generation (xcde.ini frame_gen = 0/1)
    int ui_lang;         // [XCDE] launcher and F1-menu language: 0 Spanish, 1 English (xcde.ini launcher_lang = es | en)
    int stick_deadzone;  // [XCDE] % of the stick's travel read as centred (xcde.ini stick_deadzone = 0-30, default 0: raw)
    int cutscene_mode;   // [XCDE] T224: 0 cutscenes at the FPS setting, 1 at 30, 2 at 30 + FSR 3 frame generation (xcde.ini cutscenes = same|30|30fg)
    int menu_navigation_speed; // [XCDE] LINUX-014: MENU_NAV_*, normal=30-style, fast=60-style repeat
    bool quickstep_slot; // [XCDE] LINUX-039: character-owned Quick Step slot, opt-in
    // [XCDE] LINUX-072: opt-in XCDE cheats, fixed integer percentages (100 = 1x).
    // These are runtime preferences; the native game save format is unchanged.
    bool cheat_damage_dealt, cheat_damage_received;
    bool cheat_exp, cheat_ap, cheat_sp, cheat_gold;
    int cheat_damage_dealt_percent, cheat_damage_received_percent;
    int cheat_exp_percent, cheat_ap_percent, cheat_sp_percent, cheat_gold_percent;
    bool cheat_no_fall_damage;
} Settings;

enum { N_TUNIC_COLOURS = 13, N_HEART_COLOURS = 9 };
extern const char *const g_tunic_colours[N_TUNIC_COLOURS];
extern const char *const g_heart_colours[N_HEART_COLOURS];

extern Settings g_settings;
extern int g_window_w, g_window_h;  // [XCDE] windowed size (xcde.ini "window = WxH")

void settings_load(void);
void settings_save(void);
// The language code to serve the game ("es", "en-US", ...): the setting, or the host locale for LANG_AUTO
const char *settings_language(void);
// That code's name for the menu ("Spanish")
const char *settings_language_name(void);
