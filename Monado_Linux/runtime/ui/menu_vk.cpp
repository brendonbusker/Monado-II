// [XCDE] In-game settings overlay (runtime/ui/menu.h; Windows / Vulkan): F1 opens and closes it (Esc closes), the
// launcher's options over the running game. Dear ImGui drawn by its Vulkan backend into the window image after the
// game image (device.c calls menu_render inside that rendering). Events arrive on the main thread and are queued for
// the render thread, which owns the ImGui context; while the menu is open the game sees no keyboard / mouse / pad
// input. Options that the renderer reads every frame apply at once (resolution, upscaler and its quality, SMAA, depth
// of field, volume, FPS in the title, V-Sync); the others are saved to xcde.ini and apply at the next start
// (marked "al reiniciar"). "Guardar" writes xcde.ini (settings_save) for the launcher and the next start.
#include <SDL3/SDL.h>
#include <math.h>
#include <stdlib.h>
#include <mutex>
#include <string.h>

#include "imgui.h"
#include "imgui_impl_vulkan.h"
#ifdef __linux__
#include "quality_controls_linux.h" // [XCDE] LINUX-103
#include "cheats_controls_linux.h"
#include "../cheats_options.h"
#endif
#include "fps_meter.h" // [XCDE] LINUX-094: sample real game frames, not UI presents.
#include "fps_overlay_draw.h"
#ifdef __linux__
#include "fps_fonts.h" // [XCDE] LINUX-124: generated from the bundled licensed DejaVu fonts.
#endif
#ifdef __linux__
#include "fps_output_diagnostics_linux.h"
#endif

extern "C" {
#include "../nvn/vulkan/vk.h"
#include "../nvn/vulkan/temporal.h"
#include "../settings.h"
#include "graphics_options.h"  // [XCDE] LINUX-006: available modes, retaining settings' C linkage
#include "menu.h"
bool vk_imgui_backend_init(void);
void vk_imgui_backend_shutdown(void);
void input_reset(void);
void vk_request_swapchain_recreate(void);
bool dlss_available(void);
bool tmp_fg_supported(void);
bool vk_external_fps(double *rate,bool *ready);
#ifdef __linux__
bool vk_external_fps_snapshot(MonadoPresentObserverSnapshot *snapshot,uint64_t *now_ns);
#endif
}

static std::mutex q_lock;
static SDL_Event q[256];
static int q_n;
static volatile bool open_, want_window;
static bool fs_applied = false, fs_init;

// [XCDE] LINUX-094: the FPS display owns a separate, noninteractive context.
// Device presentation calls it after interpolation, so it never enters FG history.
static FpsMeter fps_meter;
static FpsPresentMeter fps_present_meter; // [XCDE] LINUX-097: successful outputs, not configured FPS
static bool fps_generation_mode, fps_external_mode;
static bool fps_has_frame, fps_backend_failed;
static ImGuiContext *fps_context;
static ImFont *fps_number_font, *fps_label_font;
static uint64_t fps_last_ui_time;
#ifdef __linux__
static FpsOutputLogClock fps_output_log_clock;
static uint64_t fps_meter_epoch;
static MonadoPresentObserverSnapshot fps_driver_snapshot;
static uint64_t fps_driver_now_ns;
static bool fps_driver_available;
static void fps_bump_meter_epoch(void) {if(fps_meter_epoch!=UINT64_MAX)++fps_meter_epoch;}
#endif

static bool fps_sample_enabled(void) {
#ifdef __linux__
    if(g_settings.frame_gen||g_settings.cutscene_mode==2||g_settings.frame_gen_smooth_motion||fps_external_mode)return true;
#endif
    return g_settings.show_fps_overlay;
}

extern "C" void fps_overlay_reset(void) {
    fps_meter_reset(&fps_meter);
    fps_present_meter_reset(&fps_present_meter);
    fps_generation_mode = fps_external_mode = false;
    fps_has_frame = false;
    fps_backend_failed = false;
    fps_last_ui_time = 0;
#ifdef __linux__
    fps_bump_meter_epoch();
    fps_driver_snapshot={};fps_driver_now_ns=0;fps_driver_available=false;
#endif
}

extern "C" void fps_overlay_frame(uint64_t now) {
    if (!fps_sample_enabled()) {
        if (fps_has_frame) fps_overlay_reset();
        return;
    }
#ifdef __linux__
    if(fps_meter.started&&(now<fps_meter.last_ns||now-fps_meter.last_ns>UINT64_C(2000000000)))fps_bump_meter_epoch();
#endif
    fps_present_meter_tick(&fps_present_meter, now);
    fps_meter_frame(&fps_meter, now);
    fps_has_frame = true;
}

// Mode changes invalidate only output history; native rendering remains an
// independently measured clock. The selected integrated mode includes warmup.
extern "C" void fps_overlay_generation(bool active, bool external) {
#ifndef __linux__
    active = active && g_settings.show_fps_overlay;
#endif
    external = active && external;
    if (active != fps_generation_mode || external != fps_external_mode) {
        fps_present_meter_reset(&fps_present_meter);
#ifdef __linux__
        fps_bump_meter_epoch();
#endif
    }
    fps_generation_mode = active;
    fps_external_mode = external;
}

extern "C" void fps_overlay_present(uint64_t now, bool generated, bool repeated) {
    if (!fps_sample_enabled() || !fps_has_frame || (generated && repeated)) return;
    fps_present_meter_event(&fps_present_meter, now, generated ? FPS_PRESENT_GENERATED :
                            repeated ? FPS_PRESENT_REPEATED : FPS_PRESENT_NATIVE);
}

#ifdef __linux__
// Render-thread tick, called once per real frame independently of ImGui drawing.
// The very same validated driver snapshot supplies the next overlay and log row.
extern "C" void fps_overlay_diagnostics(uint64_t now,unsigned method,bool fsr_inputs_ready) {
    static const bool precompile=getenv("XCDE_PRECOMPILING")!=nullptr;
    if(precompile||!fps_has_frame||(method!=1&&method!=2))return;
    bool due=fps_output_log_due(&fps_output_log_clock,now,true);
    if(method==2&&(due||g_settings.show_fps_overlay))
        fps_driver_available=vk_external_fps_snapshot(&fps_driver_snapshot,&fps_driver_now_ns);
    else if(method!=2) {fps_driver_available=false;fps_driver_snapshot={};fps_driver_now_ns=0;}
    if(!due)return;
    FpsOutputLogSample sample{};
    sample.sdl_ns=now;sample.meter_epoch=fps_meter_epoch;sample.method=method;
    sample.game_ready=fps_meter_value(&fps_meter,&sample.game_fps);
    sample.fsr_inputs_ready=fsr_inputs_ready;
    sample.output_available=method!=2||fps_driver_available;
    memcpy(sample.application_accepted,fps_present_meter.accepted,sizeof sample.application_accepted);
    if(method==2) {
        sample.driver=fps_driver_snapshot;sample.driver_now_ns=fps_driver_now_ns;
        sample.output_ready=(sample.driver.flags&MONADO_PRESENT_OBSERVER_READY)!=0;
        sample.output_fps=sample.driver.output_fps;
    } else {
        sample.output_ready=fps_present_meter_value(&fps_present_meter,&sample.application);
        sample.output_fps=sample.application.total;
    }
    char line[1152];
    if(fps_output_log_format(line,sizeof line,getenv("MONADO_RUN_ID"),&sample))fputs(line,stderr);
}
#endif

extern "C" bool fps_overlay_visible(void) {
    return g_settings.show_fps_overlay && g_settings.fps_overlay_mode > FPS_OVERLAY_OFF &&
           g_settings.fps_overlay_mode < FPS_OVERLAY_COUNT && fps_has_frame && !fps_backend_failed;
}

extern "C" void fps_overlay_render(void *cmd, uint32_t w, uint32_t h) {
    if (!fps_overlay_visible() || !w || !h) return;
    ImGuiContext *previous = ImGui::GetCurrentContext();
    if (!fps_context) {
        fps_context = ImGui::CreateContext();
        ImGui::SetCurrentContext(fps_context);
        ImGuiIO &io = ImGui::GetIO();
        io.IniFilename = nullptr; io.LogFilename = nullptr;
        io.ConfigFlags = ImGuiConfigFlags_NoMouse | ImGuiConfigFlags_NoKeyboard | ImGuiConfigFlags_NoMouseCursorChange;
        io.MouseDrawCursor = false;
#ifdef __linux__
        ImFontConfig config{}; config.SizePixels = 32.0f; config.FontDataOwnedByAtlas = false;
        // One small Latin atlas is sufficient for numeric values and the fixed
        // English measurement labels. Embedded bytes outlive every FPS context.
        static const ImWchar glyphs[] = {0x20, 0xff, 0};
        fps_label_font = io.Fonts->AddFontFromMemoryTTF((void *)fps_font_sans, sizeof fps_font_sans, 32.0f, &config, glyphs);
        fps_number_font = io.Fonts->AddFontFromMemoryTTF((void *)fps_font_serif, sizeof fps_font_serif, 72.0f, &config, glyphs);
        if (!fps_label_font || !fps_number_font) {
            ImGui::DestroyContext(fps_context); fps_context = nullptr; fps_backend_failed = true;
            fps_label_font = fps_number_font = nullptr;
            ImGui::SetCurrentContext(previous); return;
        }
#else
        ImFontConfig config{}; config.SizePixels = 48.0f;
        fps_label_font = fps_number_font = io.Fonts->AddFontDefault(&config);
#endif
        if (!vk_imgui_backend_init()) {
            ImGui::DestroyContext(fps_context); fps_context = nullptr; fps_backend_failed = true;
            fps_label_font = fps_number_font = nullptr;
            ImGui::SetCurrentContext(previous); return;
        }
        if (!ImGui_ImplVulkan_CreateFontsTexture()) {
            vk_imgui_backend_shutdown();
            ImGui::DestroyContext(fps_context); fps_context = nullptr; fps_backend_failed = true;
            fps_label_font = fps_number_font = nullptr;
            ImGui::SetCurrentContext(previous); return;
        }
    }
    ImGui::SetCurrentContext(fps_context);
    ImGuiIO &io = ImGui::GetIO();
    io.DisplaySize = ImVec2((float)w, (float)h);
    uint64_t now = SDL_GetTicksNS();
    io.DeltaTime = fps_last_ui_time && now > fps_last_ui_time ? (float)((now - fps_last_ui_time) / 1e9) : 1.0f / 60;
    fps_last_ui_time = now;
    ImGui_ImplVulkan_NewFrame(); ImGui::NewFrame();
    double value = 0;
    bool ready = fps_meter_value(&fps_meter, &value);
    fps_overlay_detail::Rates rates;
    rates.game_ready = ready; rates.game = value;
    rates.generation = fps_generation_mode; rates.external = fps_external_mode;
    FpsPresentRates output;
    rates.output_ready = fps_present_meter_value(&fps_present_meter, &output);
    rates.output = output.total;
    rates.generated_ready = rates.output_ready && !rates.external;
    rates.generated = output.generated;
    if(rates.external) {
#ifdef __linux__
        rates.external_measured=fps_driver_available;
        rates.output=fps_driver_snapshot.output_fps;
        rates.output_ready=fps_driver_available&&(fps_driver_snapshot.flags&MONADO_PRESENT_OBSERVER_READY)!=0;
#else
        rates.external_measured=vk_external_fps(&rates.output,&rates.output_ready);
#endif
    }
#ifdef __linux__
    static_assert(int(FPS_OVERLAY_OFF) == int(fps_overlay_detail::Off) && int(FPS_OVERLAY_NUMBER) == int(fps_overlay_detail::Number) &&
                  int(FPS_OVERLAY_COMPACT) == int(fps_overlay_detail::Compact) && int(FPS_OVERLAY_DETAILED) == int(fps_overlay_detail::Detailed),
                  "FPS overlay setting and presentation modes must agree");
    fps_overlay_detail::draw(g_settings.fps_overlay_mode, rates, (float)w, (float)h,
                             fps_number_font, fps_label_font);
#else
    fps_overlay_detail::draw(true, rates, (float)w, (float)h);
#endif
    ImGui::Render();
    ImGui_ImplVulkan_RenderDrawData(ImGui::GetDrawData(), (VkCommandBuffer)cmd);
    ImGui::SetCurrentContext(previous);
}

static bool is_input(Uint32 t) {
    switch (t) {
    case SDL_EVENT_KEY_DOWN: case SDL_EVENT_KEY_UP: case SDL_EVENT_TEXT_INPUT: case SDL_EVENT_MOUSE_MOTION:
    case SDL_EVENT_MOUSE_BUTTON_DOWN: case SDL_EVENT_MOUSE_BUTTON_UP: case SDL_EVENT_MOUSE_WHEEL:
    case SDL_EVENT_GAMEPAD_BUTTON_DOWN: case SDL_EVENT_GAMEPAD_BUTTON_UP: case SDL_EVENT_GAMEPAD_AXIS_MOTION:
        return true;
    default: return false;
    }
}

extern "C" bool menu_handle_event(const SDL_Event *e) {
    if (e->type == SDL_EVENT_KEY_DOWN && !e->key.repeat &&
        (e->key.scancode == SDL_SCANCODE_F1 || (open_ && e->key.scancode == SDL_SCANCODE_ESCAPE))) {
        open_ = !open_ && e->key.scancode == SDL_SCANCODE_F1;
        input_reset();  // (keys held when the menu opened / closed are released for the game)
        return true;
    }
    if (!open_ || !is_input(e->type)) return false;
    std::lock_guard<std::mutex> g(q_lock);
    if (q_n < 256) q[q_n++] = *e;
    return true;
}

extern "C" bool menu_is_open(void) { return open_; }

extern "C" void menu_apply_window_requests(void *sdl_window) {
    if (!fs_init) { fs_init = true; fs_applied = g_settings.fullscreen; }
    if (!want_window || !sdl_window) return;
    want_window = false;
    if (fs_applied != g_settings.fullscreen) {
        SDL_SetWindowFullscreen((SDL_Window *)sdl_window, g_settings.fullscreen);
        fs_applied = g_settings.fullscreen;
    }
}

extern "C" void menu_test_open(void) { open_ = true; }

static ImGuiKey key_of(SDL_Scancode s) {
    switch (s) {
    case SDL_SCANCODE_TAB: return ImGuiKey_Tab;
    case SDL_SCANCODE_LEFT: return ImGuiKey_LeftArrow;
    case SDL_SCANCODE_RIGHT: return ImGuiKey_RightArrow;
    case SDL_SCANCODE_UP: return ImGuiKey_UpArrow;
    case SDL_SCANCODE_DOWN: return ImGuiKey_DownArrow;
    case SDL_SCANCODE_RETURN: return ImGuiKey_Enter;
    case SDL_SCANCODE_KP_ENTER: return ImGuiKey_KeypadEnter;
    case SDL_SCANCODE_SPACE: return ImGuiKey_Space;
    case SDL_SCANCODE_ESCAPE: return ImGuiKey_Escape;
    case SDL_SCANCODE_BACKSPACE: return ImGuiKey_Backspace;
    case SDL_SCANCODE_LSHIFT: return ImGuiKey_LeftShift;
    case SDL_SCANCODE_RSHIFT: return ImGuiKey_RightShift;
    case SDL_SCANCODE_LCTRL: return ImGuiKey_LeftCtrl;
    case SDL_SCANCODE_RCTRL: return ImGuiKey_RightCtrl;
    default: return ImGuiKey_None;
    }
}
static ImGuiKey pad_key(Uint8 b) {
    switch (b) {
    case SDL_GAMEPAD_BUTTON_SOUTH: return ImGuiKey_GamepadFaceDown;
    case SDL_GAMEPAD_BUTTON_EAST: return ImGuiKey_GamepadFaceRight;
    case SDL_GAMEPAD_BUTTON_WEST: return ImGuiKey_GamepadFaceLeft;
    case SDL_GAMEPAD_BUTTON_NORTH: return ImGuiKey_GamepadFaceUp;
    case SDL_GAMEPAD_BUTTON_DPAD_UP: return ImGuiKey_GamepadDpadUp;
    case SDL_GAMEPAD_BUTTON_DPAD_DOWN: return ImGuiKey_GamepadDpadDown;
    case SDL_GAMEPAD_BUTTON_DPAD_LEFT: return ImGuiKey_GamepadDpadLeft;
    case SDL_GAMEPAD_BUTTON_DPAD_RIGHT: return ImGuiKey_GamepadDpadRight;
    case SDL_GAMEPAD_BUTTON_LEFT_SHOULDER: return ImGuiKey_GamepadL1;
    case SDL_GAMEPAD_BUTTON_RIGHT_SHOULDER: return ImGuiKey_GamepadR1;
    case SDL_GAMEPAD_BUTTON_START: return ImGuiKey_GamepadStart;
    default: return ImGuiKey_None;
    }
}

// Events queued by the main thread -> ImGui IO (render thread). Mouse positions: window points -> pixels.
static void feed(ImGuiIO &io, uint32_t w, uint32_t h) {
    SDL_Event ev[256];
    int n;
    {
        std::lock_guard<std::mutex> g(q_lock);
        n = q_n;
        memcpy(ev, q, sizeof(SDL_Event) * n);
        q_n = 0;
    }
    for (int i = 0; i < n; i++) {
        const SDL_Event &e = ev[i];
        float sx = 1, sy = 1;
        SDL_Window *win = SDL_GetWindowFromID(e.motion.windowID);
        if (win) {
            int ww, wh;
            SDL_GetWindowSize(win, &ww, &wh);
            if (ww > 0 && wh > 0) { sx = (float)w / ww; sy = (float)h / wh; }
        }
        switch (e.type) {
        case SDL_EVENT_MOUSE_MOTION: io.AddMousePosEvent(e.motion.x * sx, e.motion.y * sy); break;
        case SDL_EVENT_MOUSE_BUTTON_DOWN: case SDL_EVENT_MOUSE_BUTTON_UP: {
            int b = e.button.button == SDL_BUTTON_LEFT ? 0 : e.button.button == SDL_BUTTON_RIGHT ? 1 : 2;
            io.AddMousePosEvent(e.button.x * sx, e.button.y * sy);
            io.AddMouseButtonEvent(b, e.type == SDL_EVENT_MOUSE_BUTTON_DOWN);
            break;
        }
        case SDL_EVENT_MOUSE_WHEEL: io.AddMouseWheelEvent(e.wheel.x, e.wheel.y); break;
        case SDL_EVENT_KEY_DOWN: case SDL_EVENT_KEY_UP: {
            ImGuiKey k = key_of(e.key.scancode);
            if (k != ImGuiKey_None) io.AddKeyEvent(k, e.type == SDL_EVENT_KEY_DOWN);
            break;
        }
        case SDL_EVENT_TEXT_INPUT: io.AddInputCharactersUTF8(e.text.text); break;
        case SDL_EVENT_GAMEPAD_BUTTON_DOWN: case SDL_EVENT_GAMEPAD_BUTTON_UP: {
            ImGuiKey k = pad_key(e.gbutton.button);
            if (k != ImGuiKey_None) io.AddKeyEvent(k, e.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN);
            if (e.gbutton.button == SDL_GAMEPAD_BUTTON_EAST && e.type == SDL_EVENT_GAMEPAD_BUTTON_DOWN) open_ = false;  // (B: back to the game)
            break;
        }
        default: break;
        }
    }
}

// [XCDE] the menu's language follows the launcher's (xcde.ini launcher_lang; g_settings.ui_lang 1 = English): the
// Spanish text is the key, T() gives the English one.
static const char *const k_en[][2] = {
    {"Igual que la ventana (recomendado)", "Match the window (recommended)"}, {"1x - 720p (como Switch)", "1x - 720p (like Switch)"},
    {"75 % de la ventana", "75 % of the window"}, {"50 % de la ventana", "50 % of the window"},
    {"Dinámica (mantiene 60 FPS)", "Dynamic (holds 60 FPS)"}, {"Opciones  (F1 / Esc para volver al juego)", "Options  (F1 / Esc to go back to the game)"},
    {"Gráficos", "Graphics"}, {"Pantalla", "Display"}, {"Pantalla completa", "Fullscreen"},
    {"Resolución y escalado", "Resolution and scaling"}, {"Resolución interna", "Internal resolution"},
    {"Bilineal (suave)", "Bilinear (soft)"}, {"AMD FSR 1.0 (nítido)", "AMD FSR 1.0 (sharp)"}, {"Escalado / antialiasing", "Upscaling / anti-aliasing"},
    {"FSR 3, DLSS y generación de frames no disponibles en Linux.", "FSR 3, DLSS and frame generation are unavailable on Linux."},
    {"DLSS se carga al iniciar el juego: hasta reiniciar se usa FSR 3.1.", "DLSS loads when the game starts: FSR 3.1 is used until a restart."},
    {"Nativo (solo antialiasing)", "Native (anti-aliasing only)"}, {"Calidad (67 %)", "Quality (67 %)"}, {"Equilibrado (59 %)", "Balanced (59 %)"},
    {"Rendimiento (50 %)", "Performance (50 %)"}, {"Ultra rendimiento (33 %)", "Ultra performance (33 %)"}, {"Calidad del escalado", "Upscaling quality"},
    {"Generación de frames (FSR 3; activarla por primera vez: al reiniciar)", "Frame generation (FSR 3; the first time it is enabled: after a restart)"},
    {"Calidad", "Quality"}, {"Antialiasing SMAA", "SMAA anti-aliasing"}, {"(no se usa con FSR 3.1 / DLSS)", "(not used with FSR 3.1 / DLSS)"},
    {"Profundidad de campo", "Depth of field"},
    {"Antialiasing y desenfoque de movimiento del juego (al reiniciar)", "The game's anti-aliasing and motion blur (after a restart)"},
    {"Mostrar FPS en la barra de título", "Show FPS in the title bar"}, {"Mostrar FPS en pantalla", "Show FPS on screen"},
    {"Desactivado", "Off"}, {"Solo número", "Number only"}, {"HUD compacto", "Compact HUD"}, {"Panel detallado", "Detailed panel"},
    {"Velocidad", "Speed"}, {"30 (como en Switch)", "30 (like Switch)"},
    {"Sin límite", "Unlimited"}, {"FPS (al reiniciar)", "FPS (after a restart)"}, {"V-Sync (con 30 / 60 FPS)", "V-Sync (at 30 / 60 FPS)"},
    {"Volumen", "Volume"}, {"Audio de los vídeos (al reiniciar)", "Video sound (after a restart)"}, {"Controles", "Controls"},
    {"La asignación de teclas y botones se cambia en el launcher (Play Monado.bat), pestaña Controles.",
     "Keys and buttons are remapped in the launcher, Controls tab."},
    {"Guardar", "Save"}, {"Volver al juego", "Back to the game"}, {"Guardado en xcde.ini", "Saved to xcde.ini"},
};
static const char *T(const char *es) {
    if (g_settings.ui_lang != 1) return es;
    for (const auto &e : k_en) if (!strcmp(e[0], es)) return e[1];
    return es;
}
struct TList { const char *p[8]; };
static TList TL(const char *const *a, int n) { TList t{}; for (int i = 0; i < n && i < 8; i++) t.p[i] = T(a[i]); return t; }

static const char *const k_res_ui[] = {"Igual que la ventana (recomendado)", "1x - 720p (como Switch)", "2x - 1440p", "3x - 2160p",
                                       "75 % de la ventana", "50 % de la ventana", "Dinámica (mantiene 60 FPS)"};
static const int k_res_mode[] = {RES_MATCH, 1, 2, 3, RES_Q75, RES_Q50, RES_DYNAMIC};

static void ui(void) {
    static bool saved_note;
    ImGuiViewport *vp = ImGui::GetMainViewport();
    ImGui::SetNextWindowPos(ImVec2(vp->Size.x * 0.5f, vp->Size.y * 0.5f), ImGuiCond_Always, ImVec2(0.5f, 0.5f));
    ImGui::SetNextWindowSize(ImVec2(vp->Size.y * 0.95f, vp->Size.y * 0.8f), ImGuiCond_Always);
    ImGui::SetNextWindowBgAlpha(0.92f);
    ImGui::Begin(T("Opciones  (F1 / Esc para volver al juego)"), nullptr, ImGuiWindowFlags_NoCollapse | ImGuiWindowFlags_NoMove |
                 ImGuiWindowFlags_NoResize | ImGuiWindowFlags_NoSavedSettings);
    if (ImGui::BeginTabBar("tabs")) {
        if (ImGui::BeginTabItem(T("Gráficos"))) {
#ifdef __linux__
            if(monado_quality_controls_linux(&g_settings,g_settings.ui_lang==1))xcde_graphics_publish(&g_settings.graphics);
#endif
            ImGui::SeparatorText(T("Pantalla"));
            if (ImGui::Checkbox(T("Pantalla completa"), &g_settings.fullscreen)) want_window = true;
            ImGui::SeparatorText(T("Resolución y escalado"));
            int ri = 0;
            for (int i = 0; i < 7; i++) if (k_res_mode[i] == g_settings.res_mode) ri = i;
            if (ImGui::Combo(T("Resolución interna"), &ri, TL(k_res_ui, 7).p, 7)) g_settings.res_mode = k_res_mode[ri];
            int ui_ = 0;
            for (int i = 0; i < MENU_UPSCALER_COUNT; i++) if (menu_upscale_values[i] == g_settings.upscaler) ui_ = i;
            if (ImGui::Combo(T("Escalado / antialiasing"), &ui_, TL(menu_upscale_names, MENU_UPSCALER_COUNT).p,
                             MENU_UPSCALER_COUNT)) {
                g_settings.upscaler = menu_upscale_values[ui_];
#if defined(__linux__) && defined(XCDE_LINUX_FRAMEGEN)
                if (g_settings.upscaler != UPSCALE_DLSS && g_settings.upscaler != UPSCALE_FSR3 && g_settings.upscaler!=UPSCALE_FSR4_LITE) {
                    bool was_fg = g_settings.frame_gen || g_settings.cutscene_mode == 2;
                    g_settings.frame_gen = false;
                    if (g_settings.cutscene_mode == 2) g_settings.cutscene_mode = 1;
                    if (was_fg) vk_request_swapchain_recreate();
                }
#endif
            }
#ifdef __linux__
#ifndef XCDE_LINUX_FSR3
            ImGui::TextDisabled("Native FSR 3.1 component is not available in this build.");
#endif
            if (g_settings.upscaler == UPSCALE_DLSS || g_settings.upscaler == UPSCALE_FSR3 || g_settings.upscaler==UPSCALE_FSR4_LITE) {
#ifdef XCDE_LINUX_DLSS
                if (g_settings.upscaler==UPSCALE_DLSS && !dlss_available()) ImGui::TextColored(ImVec4(1, .8f, .3f, 1), "DLSS requires a compatible RTX GPU and a game restart; using FSR 3 when available, otherwise spatial scaling.");
#endif
#ifdef XCDE_LINUX_FSR3
                if(g_settings.upscaler==UPSCALE_FSR3 && !tmp_fsr3_supported())
                    ImGui::TextColored(ImVec4(1,.8f,.3f,1),"The native FSR 3.1 component failed its identity/API check; using spatial scaling.");
#endif
#ifdef XCDE_LINUX_FSR4
                if(g_settings.upscaler==UPSCALE_FSR4_LITE)ImGui::TextWrapped("%s",tmp_fsr4_status());
#endif
                const char *uq[] = {"Native AA (100%)", "Quality (67%)", "Balanced (59%)", "Performance (50%)", "Ultra Performance (33%)"};
                ImGui::Combo(T("Calidad del escalado"), &g_settings.upscale_quality, uq, 5);
                ImGui::TextDisabled("%s","Native uses temporal antialiasing at 100%. Match the window uses the selected SR quality.");
#ifdef XCDE_LINUX_FRAMEGEN
                const char *smooth = getenv("NVPRESENT_ENABLE_SMOOTH_MOTION");
                bool external = smooth && !strcmp(smooth, "1");
                ImGui::BeginDisabled(external || g_settings.frame_gen_smooth_motion || !tmp_fg_supported());
                if (ImGui::Checkbox("Frame generation (FSR 3, 2x, experimental)", &g_settings.frame_gen))
                    vk_request_swapchain_recreate();
                ImGui::BeginDisabled(!g_settings.frame_gen);
                ImGui::Checkbox("Match display with 2x generation", &g_settings.frame_gen_match_display);
                ImGui::EndDisabled();
                ImGui::EndDisabled();
                ImGui::TextWrapped("2x generates one intermediate image. Match display limits real FPS to half the refresh rate, up to your FPS limit. Adds latency.");
                if (external) ImGui::TextDisabled("NVIDIA Smooth Motion is requested from the driver. Change methods in the launcher and restart.");
                else if (g_settings.frame_gen_smooth_motion) ImGui::TextDisabled("NVIDIA Smooth Motion selected; restart from the launcher to apply it.");
#endif
            }
#else
            if (g_settings.upscaler == UPSCALE_DLSS && !dlss_available())
                ImGui::TextColored(ImVec4(1, 0.8f, 0.3f, 1), T("DLSS se carga al iniciar el juego: hasta reiniciar se usa FSR 3.1."));
            if (g_settings.upscaler == UPSCALE_FSR3 || g_settings.upscaler == UPSCALE_DLSS) {
                static const char *uq[] = {"Nativo (solo antialiasing)", "Calidad (67 %)", "Equilibrado (59 %)", "Rendimiento (50 %)",
                                           "Ultra rendimiento (33 %)"};
                ImGui::Combo(T("Calidad del escalado"), &g_settings.upscale_quality, TL(uq, 5).p, 5);
                ImGui::BeginDisabled(g_settings.upscaler != UPSCALE_FSR3);
                ImGui::Checkbox(T("Generación de frames (FSR 3; activarla por primera vez: al reiniciar)"), &g_settings.frame_gen);
                ImGui::EndDisabled();
            }
#endif
            ImGui::SeparatorText(T("Calidad"));
            bool smaa = g_settings.antialias == AA_SMAA;
            if (ImGui::Checkbox(T("Antialiasing SMAA"), &smaa)) g_settings.antialias = smaa ? AA_SMAA : AA_OFF;
#ifndef __linux__
            if (g_settings.upscaler == UPSCALE_FSR3 || g_settings.upscaler == UPSCALE_DLSS || g_settings.upscaler==UPSCALE_FSR4_LITE) ImGui::SameLine(), ImGui::TextDisabled("(not used with temporal reconstruction)");
#endif
            bool dof = !g_settings.dof_off;
            if (ImGui::Checkbox(T("Profundidad de campo"), &dof)) g_settings.dof_off = !dof;
            ImGui::Checkbox(T("Antialiasing y desenfoque de movimiento del juego (al reiniciar)"), &g_settings.game_blur);
            ImGui::Checkbox(T("Mostrar FPS en la barra de título"), &g_settings.show_fps);
#ifdef __linux__
            static const char *fps_overlay_modes[] = {"Desactivado", "Solo número", "HUD compacto", "Panel detallado"};
            int fps_overlay_mode = g_settings.fps_overlay_mode;
            if (ImGui::Combo(T("Mostrar FPS en pantalla"), &fps_overlay_mode, TL(fps_overlay_modes, FPS_OVERLAY_COUNT).p, FPS_OVERLAY_COUNT)) {
                g_settings.fps_overlay_mode = fps_overlay_mode;
                g_settings.show_fps_overlay = fps_overlay_mode != FPS_OVERLAY_OFF;
            }
#else
            ImGui::Checkbox(T("Mostrar FPS en pantalla"), &g_settings.show_fps_overlay);
#endif
            ImGui::SetItemTooltip("Game counts rendered frames. Output counts successful presentation requests, not physical scanout.\nMeasured FG readings are also logged when this display is off. NVIDIA generated-only FPS is unavailable.");
            ImGui::SeparatorText(T("Velocidad"));
            static const int fpsv[] = {30, 60, 120, 144, 165, 0};
            static const char *fpsu[] = {"30 (como en Switch)", "60", "120", "144", "165", "Sin límite"};
            int fi = 0;
            for (int i = 0; i < 6; i++) if (fpsv[i] == g_settings.fps) fi = i;
            if (ImGui::Combo(T("FPS (al reiniciar)"), &fi, TL(fpsu, 6).p, 6)) g_settings.fps = fpsv[fi];
            const char *vsync_label = (g_settings.frame_gen || g_settings.cutscene_mode == 2)
                ? "V-Sync (also paces FSR frame generation)" : T("V-Sync (con 30 / 60 FPS)");
            if (ImGui::Checkbox(vsync_label, &g_settings.vsync)) vk_request_swapchain_recreate();
            ImGui::EndTabItem();
        }
        if (ImGui::BeginTabItem(T("Audio"))) {
            int vol = (int)lroundf(g_settings.volume * 100);
            if (ImGui::SliderInt(T("Volumen"), &vol, 0, 200, "%d %%")) g_settings.volume = vol / 100.0f;
            ImGui::Checkbox(T("Audio de los vídeos (al reiniciar)"), &g_settings.movie_audio);
            ImGui::EndTabItem();
        }
        if (ImGui::BeginTabItem(T("Controles"))) {
#ifdef __linux__
            ImGui::Checkbox(g_settings.ui_lang?"Controller vibration":"Vibración del mando",&g_settings.input_rumble);
#endif
            ImGui::TextWrapped("%s", T("La asignación de teclas y botones se cambia en el launcher (Play Monado.bat), pestaña Controles."));
            ImGui::EndTabItem();
        }
#ifdef __linux__
        if (ImGui::BeginTabItem(g_settings.ui_lang ? "Cheats" : "Trucos")) {
            if (monado_cheat_controls_linux(&g_settings, g_settings.ui_lang == 1))
                xcde_cheats_publish(&g_settings);
            ImGui::EndTabItem();
        }
#endif
        ImGui::EndTabBar();
    }
    ImGui::Separator();
    if (ImGui::Button(T("Guardar"))) { settings_save(); saved_note = true; }
    ImGui::SameLine();
    if (ImGui::Button(T("Volver al juego"))) { open_ = false; input_reset(); }
    if (saved_note) { ImGui::SameLine(); ImGui::TextDisabled("%s", T("Guardado en xcde.ini")); }
    ImGui::End();
}

extern "C" void menu_render(void *cmd, uint32_t w, uint32_t h) {
    static ImGuiContext *ctx;
    static float font_h;
    static uint64_t t_last;
    if (!open_) return;
    if (!ctx) {
        ctx = ImGui::CreateContext();
        ImGui::SetCurrentContext(ctx);
        ImGuiIO &io = ImGui::GetIO();
        io.IniFilename = nullptr;
        io.ConfigFlags |= ImGuiConfigFlags_NavEnableKeyboard | ImGuiConfigFlags_NavEnableGamepad;
        io.BackendFlags |= ImGuiBackendFlags_HasGamepad;
        font_h = fmaxf(16.0f, h / 1080.0f * 22.0f);
#ifdef __linux__
        // [XCDE] LINUX-006: the bundled font avoids a Windows-only file lookup.
        ImFontConfig font_config{};
        font_config.SizePixels = font_h;
        io.Fonts->AddFontDefault(&font_config);
#else
        if (!io.Fonts->AddFontFromFileTTF("C:\\Windows\\Fonts\\segoeui.ttf", font_h, nullptr, io.Fonts->GetGlyphRangesDefault()))
            io.Fonts->AddFontDefault();
#endif
        ImGui::StyleColorsDark();
        ImGui::GetStyle().ScaleAllSizes(font_h / 16.0f);
        if (!vk_imgui_backend_init()) { ImGui::DestroyContext(ctx); ctx = nullptr; open_ = false; return; }
        ImGui_ImplVulkan_CreateFontsTexture();
    }
    ImGui::SetCurrentContext(ctx);
    ImGuiIO &io = ImGui::GetIO();
    io.DisplaySize = ImVec2((float)w, (float)h);
    uint64_t now = SDL_GetTicksNS();
    io.DeltaTime = t_last ? (float)((now - t_last) / 1e9) : 1.0f / 60;
    if (io.DeltaTime <= 0) io.DeltaTime = 1.0f / 60;
    t_last = now;
    feed(io, w, h);
    ImGui_ImplVulkan_NewFrame();
    ImGui::NewFrame();
    ui();
    ImGui::Render();
    ImGui_ImplVulkan_RenderDrawData(ImGui::GetDrawData(), (VkCommandBuffer)cmd);
}
