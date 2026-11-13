// Monado II standalone build wizard. Authored code under the MIT license.
// Uses only the licensed frontend resources; never reads game data itself.
#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>
#include "imgui.h"
#include "imgui_impl_sdl3.h"
#include "imgui_impl_sdlrenderer3.h"
#include "../launcher/theme.h"
#include "json.h"
#include <algorithm>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <fcntl.h>
#include <mutex>
#include <string>
#include <sys/stat.h>
#include <unistd.h>

namespace fs = std::filesystem;
namespace ui = launcher_theme;
namespace json = builder_json;
static std::mutex dialog_mutex;
static std::string dialog_value, dialog_error;
static int dialog_target = 0, dialog_complete = 0;
static void SDLCALL folder_callback(void *userdata, const char *const *files, int) {
    std::lock_guard<std::mutex> lock(dialog_mutex);
    dialog_complete = (int)(intptr_t)userdata;
    if (!files) dialog_error = "The folder picker could not open. You can paste the folder path instead.";
    else if (files[0]) dialog_value = files[0];
}
static bool read_file(const fs::path &path, std::string &out, size_t limit) {
    int fd = open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NOFOLLOW | O_NONBLOCK);
    if (fd < 0) return false;
    struct stat st{};
    if (fstat(fd, &st) || !S_ISREG(st.st_mode) || st.st_size < 0 || (uint64_t)st.st_size > limit) { close(fd); return false; }
    out.clear(); char bytes[4096];
    for (;;) {
        ssize_t n = read(fd, bytes, sizeof bytes);
        if (n < 0 && errno == EINTR) continue;
        if (n < 0 || out.size() + (size_t)std::max<ssize_t>(n, 0) > limit) { close(fd); return false; }
        if (!n) break; out.append(bytes, (size_t)n);
    }
    close(fd); return true;
}
static bool write_request(const fs::path &session, const std::string &data, uint64_t id) {
    fs::path tmp = session / (".request-" + std::to_string(getpid()) + "-" + std::to_string(id));
    int fd = open(tmp.c_str(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC | O_NOFOLLOW, 0600);
    if (fd < 0) return false;
    size_t off = 0;
    while (off < data.size()) {
        ssize_t n = write(fd, data.data() + off, data.size() - off);
        if (n < 0 && errno == EINTR) continue;
        if (n <= 0) break; off += (size_t)n;
    }
    bool good = off == data.size() && fsync(fd) == 0; close(fd);
    if (good) good = rename(tmp.c_str(), (session / "request.json").c_str()) == 0;
    if (!good) unlink(tmp.c_str()); return good;
}
static void heading(const char *title) {
    if (ui::heading_font) ImGui::PushFont(ui::heading_font);
    ImGui::TextUnformatted(title);
    if (ui::heading_font) ImGui::PopFont();
}
static bool primary(const char *label, ImVec2 size = ImVec2(0, 0)) {
    ImGui::PushStyleColor(ImGuiCol_Button, ui::color(0xB71D43));
    ImGui::PushStyleColor(ImGuiCol_ButtonHovered, ui::color(0xD42C53));
    ImGui::PushStyleColor(ImGuiCol_ButtonActive, ui::color(0x8E1738));
    bool result = ImGui::Button(label, size); ImGui::PopStyleColor(3); return result;
}
static void muted(const char *text) {
    ImGui::PushStyleColor(ImGuiCol_Text, ui::color(0xB5C4CF));
    ImGui::TextWrapped("%s", text); ImGui::PopStyleColor();
}
struct Wizard {
    fs::path session;
    json::Object status;
    char input[8192]{}, output[8192]{}, adoption[8192]{};
    bool dlss = true, precompile = true, details = false, advanced = false;
    bool close_requested = false, close_after_cancel = false, pending = false, inspection_ok = false;
    bool initial = true, cancel_requested = false, done = false;
    int jobs = 4, page = 0;
    uint64_t serial = 0, poll_time = 0;
    std::string request_id, request_action, phase = "welcome", error, status_json, input_previous;
    void set(char *dst, const std::string &value) { snprintf(dst, 8192, "%s", value.c_str()); }
    bool busy() const { return phase == "building" || phase == "checking" || pending; }
    void request(const char *action) {
        request_id = std::to_string(getpid()) + "-" + std::to_string(++serial);
        std::string data = "{\"id\":" + json::quote(request_id) + ",\"action\":" + json::quote(action) +
            ",\"input\":" + json::quote(input) + ",\"output\":" + json::quote(output) +
            ",\"dlss\":" + (dlss ? "true" : "false") + ",\"precompile\":" + (precompile ? "true" : "false") +
            ",\"jobs\":" + std::to_string(jobs) + "}\n";
        if (!write_request(session, data, serial)) { error = "Could not send the request. Close and reopen Monado II."; return; }
        pending = true; request_action = action; cancel_requested = !strcmp(action, "cancel"); error.clear();
        if (!strcmp(action, "inspect")) inspection_ok = false;
        if (!strcmp(action, "build")) { phase = "building"; page = 3; }
    }
    void poll() {
        uint64_t now = SDL_GetTicks(); if (!initial && now < poll_time + 100) return; poll_time = now;
        std::string data;
        if (!read_file(session / "status.json", data, 1024 * 1024) || data == status_json) return;
        try {
            auto parsed = json::parse(data);
            if (json::number(parsed, "schema") != 1) throw std::runtime_error("Unsupported builder status");
            std::string next = json::text(parsed, "phase");
            const char *known[] = {"welcome", "checking", "ready", "building", "failed", "cancelled", "complete", "installed", "input_missing"};
            bool valid = false; for (auto k : known) if (next == k) valid = true;
            if (!valid) throw std::runtime_error("Unknown builder status");
            status = std::move(parsed); status_json = data;
            std::string response = json::text(status, "request_id");
            if (initial && next == "installed") page = 4;
            initial = false;
            if (pending && response != request_id) return;
            phase = next;
            const bool terminal = phase == "failed" || phase == "cancelled" || phase == "complete" || phase == "installed" ||
                                  phase == "input_missing" ||
                                  (phase == "ready" && (request_action == "inspect" || request_action == "cancel"));
            if (response == request_id && terminal) { pending = false; cancel_requested = false; }
            if (phase == "ready") {
                inspection_ok = true;
                auto canonical = json::text(status, "input"); if (!canonical.empty()) set(input, canonical);
            }
            if (phase == "complete" || phase == "installed") {
                page = 4;
                auto canonical = json::text(status, "output"); if (!canonical.empty()) set(output, canonical);
            }
            if (phase == "input_missing") {
                if (page != 6) { set(input, ""); inspection_ok = false; }
                page = 6;
                input_previous = json::text(status, "input_previous", input_previous);
                auto owner = json::text(status, "output"); if (!owner.empty()) set(output, owner);
                if (request_action == "relocate") error = json::text(status, "message", "Could not reconnect these game files. Choose the original supported dump and try again.");
            }
            if (phase == "failed") {
                if (request_action == "relocate") page = 6;
                error = json::text(status, "message", "This step could not finish.");
                details = true;
            }
        } catch (const std::exception &e) { error = e.what(); }
    }
    void browse(SDL_Window *window, int field) {
        if (dialog_target) return;
        dialog_target = field;
        const char *value = field == 1 ? input : field == 2 ? output : adoption;
        SDL_ShowOpenFolderDialog(folder_callback, (void *)(intptr_t)field, window, *value ? value : nullptr, false);
    }
    void apply_dialog() {
        std::lock_guard<std::mutex> lock(dialog_mutex);
        if (!dialog_complete) return;
        if (!dialog_value.empty()) {
            if (dialog_complete == 1) { set(input, dialog_value); inspection_ok = false; }
            else if (dialog_complete == 2) set(output, dialog_value);
            else set(adoption, dialog_value);
        }
        if (!dialog_error.empty()) error = dialog_error;
        dialog_value.clear(); dialog_error.clear(); dialog_complete = dialog_target = 0;
    }
    void field(const char *label, char *value, SDL_Window *window, int target, float scale) {
        ImGui::BeginDisabled(busy());
        ImGui::TextUnformatted(label); ImGui::SetNextItemWidth(ImMax(120.f, ImGui::GetContentRegionAvail().x - 104 * scale));
        if (ImGui::InputText((std::string("##") + label).c_str(), value, 8192) && target == 1) inspection_ok = false;
        ImGui::SameLine(); ImGui::BeginDisabled(dialog_target != 0);
        if (ImGui::Button((std::string("Browse##") + label).c_str(), ImVec2(92 * scale, 0))) browse(window, target);
        ImGui::EndDisabled();
        ImGui::EndDisabled();
    }
    void draw(SDL_Window *window, ImVec2 size, float scale) {
        const float margin = 24 * scale;
        const bool wide = size.x >= 1040 * scale;
        const float left = wide ? size.x * .29f : margin;
        const float top = wide ? 135 * scale : 150 * scale;
        auto draw = ImGui::GetBackgroundDrawList();
        draw->AddRectFilledMultiColor(ImVec2(0,0), size, ui::ink(0x07121D,.22f), ui::ink(0x07121D,.92f), ui::ink(0x07121D,.98f), ui::ink(0x07121D,.32f));
        draw->AddRectFilled(ImVec2(0,0), ImVec2(size.x, 122 * scale), ui::ink(0x07121D,.85f));
        ui::Layout branding{}; branding.origin = ImVec2(0,0); branding.size = size; branding.scale = scale;
        ImGui::SetNextWindowPos(ImVec2(0,0)); ImGui::SetNextWindowSize(size);
        ImGui::Begin("Monado II builder", nullptr, ImGuiWindowFlags_NoDecoration | ImGuiWindowFlags_NoMove | ImGuiWindowFlags_NoSavedSettings | ImGuiWindowFlags_NoBackground);
        ui::branding(branding, "Your game files. Your native build.");
        ImGui::SetCursorPos(ImVec2(left, top));
        ImGui::PushStyleColor(ImGuiCol_ChildBg, ui::color(0x101E2B,.98f));
        ImGui::PushStyleVar(ImGuiStyleVar_WindowPadding, ImVec2(18*scale,18*scale));
        ImGui::BeginChild("wizard", ImVec2(size.x-left-margin,size.y-top-margin), ImGuiChildFlags_Borders | ImGuiChildFlags_AlwaysUseWindowPadding);
        if (page != 0 && page != 4 && page != 5 && page != 6) {
            const char *labels[] = {"1  Game files", "2  Settings", "3  Build"};
            for (int i=0; i<3; ++i) {
                if (i) ImGui::SameLine();
                ImGui::PushStyleColor(ImGuiCol_Text, ui::color((page == i+1) ? 0xF5F6F4 : 0x91A4B4));
                ImGui::TextUnformatted(labels[i]); ImGui::PopStyleColor();
            }
            ImGui::Separator(); ImGui::Spacing();
        }
        float footer = 76 * scale;
        ImGui::BeginChild("content", ImVec2(0, ImMax(80.f, ImGui::GetContentRegionAvail().y-footer)), ImGuiChildFlags_None);
        if (page == 0) {
            ImGui::Spacing(); heading("Build your game"); ImGui::Spacing();
            ImGui::TextWrapped("Monado II turns your own Xenoblade Chronicles: Definitive Edition 2.0.0 files into a native PC game.");
            ImGui::Spacing(); muted("You need an extracted game_files folder containing exefs and romfs. Use only files dumped from your own legally obtained game and Switch.");
            ImGui::Spacing(); muted("The first build downloads the compiler and private dependencies. It can take a while and needs substantial free disk space.");
            ImGui::Spacing();
            if (primary("Set up Monado II", ImVec2(220*scale,44*scale))) { page = 1; error.clear(); }
            ImGui::Spacing();
            if (ImGui::Button("Use an existing installation")) { page = 5; error.clear(); }
        } else if (page == 1) {
            heading("Your game files");
            muted("Select the folder containing exefs and romfs. Monado II checks the supported version without modifying your files.");
            ImGui::Spacing(); field("Game files folder", input, window, 1, scale);
            ImGui::Spacing();
            if (inspection_ok) ImGui::TextColored(ui::color(0x82D5AD), "Supported game files verified.");
            else muted("Choose a folder, then check it before continuing.");
        } else if (page == 2) {
            heading("Build settings");
            muted("Choose the final installation folder before building. Your saves and settings live separately from the read-only game input.");
            ImGui::Spacing(); field("Install folder", output, window, 2, scale);
            ImGui::Spacing(); ImGui::Separator(); ImGui::Spacing();
            ui::checkbox("Include NVIDIA DLSS support", &dlss);
            muted("Optional download for compatible NVIDIA RTX GPUs. Other graphics options remain available in the launcher.");
            ImGui::Spacing(); ui::checkbox("Prepare shaders after building", &precompile);
            muted("Takes extra time now to reduce shader compilation pauses later. You can also do this from the launcher.");
            ImGui::Spacing();
            if (ImGui::CollapsingHeader("Advanced")) {
                ImGui::SetNextItemWidth(160*scale); ImGui::SliderInt("Build workers", &jobs, 1, 6);
                muted("Use fewer workers if other applications slow down or memory runs low. The standard setting is 4.");
            }
        } else if (page == 3) {
            heading(phase == "complete" ? "Your build is ready" : phase == "failed" ? "Build stopped" : phase == "cancelled" ? "Build cancelled" : "Building Monado II");
            std::string message = json::text(status, "message", "Preparing the local build...");
            ImGui::TextWrapped("%s", message.c_str()); ImGui::Spacing();
            float progress = (float)json::number(status,"progress");
            ImGui::ProgressBar(ImClamp(progress,0.f,1.f),ImVec2(-1,24*scale));
            muted("You can keep using your PC. Closing this window stops the build; retry keeps completed work and logs where it is safe to do so.");
        } else if (page == 4) {
            heading(phase == "failed" ? "Installation needs attention" : "Monado II is ready");
            std::string version = json::text(status,"version");
            if (!version.empty()) ImGui::Text("Build %s", version.c_str());
            std::string where = json::text(status,"output",output);
            ImGui::TextWrapped("Installed in %s",where.c_str());
            ImGui::Spacing(); muted("Open the settings launcher to configure graphics, controls, mods and cheats, then choose Play when you are ready.");
            ImGui::Spacing();
            ImGui::BeginDisabled(busy() || !json::boolean(status,"can_open"));
            if (primary("Open launcher", ImVec2(200*scale,44*scale))) request("open");
            ImGui::EndDisabled(); ImGui::Spacing();
            ImGui::BeginDisabled(busy());
            if (ImGui::Button("Set up another installation")) { page = 1; inspection_ok = false; set(input,""); error.clear(); }
            ImGui::EndDisabled();
        } else if (page == 5) {
            heading("Use an existing installation");
            muted("Select the Monado II folder containing Monado_Linux. Existing game files, settings and saves remain in place.");
            ImGui::Spacing(); field("Existing installation", adoption, window, 3, scale);
        } else if (page == 6) {
            heading("Locate game files");
            muted("Monado II can no longer find the game files used by this installation. Select their new location: the folder containing exefs and romfs.");
            ImGui::Spacing();
            if (!input_previous.empty()) ImGui::TextWrapped("Previous location: %s", input_previous.c_str());
            else ImGui::TextWrapped("%s", json::text(status, "detail", "The previous game files location is unavailable.").c_str());
            ImGui::Spacing(); field("Game files folder", input, window, 1, scale);
            ImGui::Spacing(); muted("Reconnect checks that these are the same supported game files. Your installed build, saves and settings are preserved. This does not start a rebuild or launch the game.");
        }
        if (busy() && page != 3) { ImGui::Spacing(); ImGui::TextWrapped("%s",json::text(status,"message","Working...").c_str()); }
        if (!error.empty()) {
            ImGui::Spacing(); ImGui::PushStyleColor(ImGuiCol_Text,ui::color(0xFFB1B8));
            ImGui::TextWrapped("%s", error.c_str()); ImGui::PopStyleColor();
        }
        if (page == 3 || !error.empty()) {
            ImGui::Spacing();
            if (details) { ImGui::SetNextItemOpen(true); details = false; }
            if (ImGui::CollapsingHeader("Details and build log")) {
                std::string log = json::text(status,"log");
                if (!log.empty()) {
                    ImGui::TextWrapped("Log: %s",log.c_str());
                    if (ImGui::Button("Copy log path")) SDL_SetClipboardText(log.c_str());
                }
                ImGui::TextWrapped("%s", json::text(status,"detail","Detailed progress will appear here.").c_str());
            }
        }
        ImGui::EndChild(); ImGui::Separator(); ImGui::Spacing();
        ImGui::BeginDisabled(busy());
        if (page == 1) {
            if (ImGui::Button("Back")) page=0; ImGui::SameLine();
            if (inspection_ok) { if (primary("Next")) { page=2; error.clear(); } }
            else { ImGui::BeginDisabled(!*input); if (primary("Check game files")) request("inspect"); ImGui::EndDisabled(); }
        } else if (page == 2) {
            if (ImGui::Button("Back")) page=1; ImGui::SameLine();
            ImGui::BeginDisabled(!*output); if (primary("Build Monado II")) request("build"); ImGui::EndDisabled();
        } else if (page == 3 && !busy()) {
            if (ImGui::Button("Back to settings")) { page=2; error.clear(); }
            ImGui::SameLine(); if (primary("Retry build")) request("build");
        } else if (page == 5) {
            if (ImGui::Button("Back")) page=0; ImGui::SameLine();
            ImGui::BeginDisabled(!*adoption);
            if (primary("Check installation")) { std::string previous=output; set(output,adoption); request("adopt"); set(output,previous); }
            ImGui::EndDisabled();
        } else if (page == 6) {
            if (ImGui::Button("Cancel")) done = true;
            ImGui::SameLine(); ImGui::BeginDisabled(!*input);
            if (primary("Reconnect")) request("relocate");
            ImGui::EndDisabled();
        }
        ImGui::EndDisabled();
        if ((page == 3 || page == 6) && busy()) {
            ImGui::BeginDisabled(cancel_requested);
            if (ImGui::Button(page == 6 ? "Cancel" : "Cancel build")) request("cancel");
            ImGui::EndDisabled();
        }
        ImGui::EndChild(); ImGui::PopStyleVar(); ImGui::PopStyleColor(); ImGui::End();
        if (close_requested && !ImGui::IsPopupOpen("Stop this operation?")) ImGui::OpenPopup("Stop this operation?");
        ImGui::SetNextWindowSize(ImVec2(440*scale,0),ImGuiCond_Appearing);
        if (ImGui::BeginPopupModal("Stop this operation?",nullptr,ImGuiWindowFlags_AlwaysAutoResize)) {
            ImGui::TextWrapped("Closing Monado II cancels the current operation safely. Your existing installation, saves and settings remain available.");
            ImGui::BeginDisabled(close_after_cancel);
            if (ImGui::Button("Keep working")) { close_requested=false; ImGui::CloseCurrentPopup(); }
            ImGui::SameLine(); if (primary("Cancel and close")) { request("cancel"); close_after_cancel=true; }
            ImGui::EndDisabled(); if (close_after_cancel) muted("Stopping safely...");
            ImGui::EndPopup();
        }
    }
};

int main(int argc,char **argv) {
    fs::path session, screenshot; int headless=0, preview=-1; bool preview_details=false;
    for (int i=1;i<argc;++i) {
        if (!strcmp(argv[i],"--preview-details")) { preview_details=true; continue; }
        if (i+1>=argc) { fprintf(stderr,"Missing builder option value\n"); return 2; }
        std::string arg=argv[i],value=argv[++i];
        if (arg=="--session") session=value;
        else if (arg=="--screenshot") screenshot=value;
        else if (arg=="--headless-frames") { char *end=nullptr; long n=strtol(value.c_str(),&end,10); if (!end || *end || n<1 || n>10000) return 2; headless=(int)n; }
        else if (arg=="--preview-page") { char *end=nullptr; long n=strtol(value.c_str(),&end,10); if (!end || *end || n<0 || n>6) return 2; preview=(int)n; }
        else { fprintf(stderr,"Unknown builder option: %s\n",arg.c_str()); return 2; }
    }
    if (!headless && (preview>=0 || preview_details)) { fprintf(stderr,"Preview options require headless rendering\n"); return 2; }
    std::error_code ec; struct stat st{};
    if (!session.is_absolute() || fs::canonical(session,ec)!=session || ec || lstat(session.c_str(),&st) || !S_ISDIR(st.st_mode) || st.st_uid!=getuid() || (st.st_mode&0077)) {
        fprintf(stderr,"Builder requires a private canonical session directory\n"); return 2;
    }
    std::string shot_name=screenshot.lexically_normal().string(), session_prefix=session.string()+"/";
    struct stat shot_stat{};
    bool fresh_shot=screenshot.empty() || (lstat(screenshot.c_str(),&shot_stat)<0 && errno==ENOENT);
    fs::path shot_parent=screenshot.empty() ? session : fs::canonical(screenshot.parent_path(),ec);
    if (!screenshot.empty() && (!headless || !screenshot.is_absolute() || !fresh_shot || ec ||
            shot_parent!=screenshot.parent_path() || shot_name.compare(0,session_prefix.size(),session_prefix)!=0)) {
        fprintf(stderr,"Screenshot must be a fresh path within the private headless session\n"); return 2;
    }
    umask(0077); SDL_SetHint(SDL_HINT_APP_ID,"monado-ii-builder");
    if (!SDL_Init(SDL_INIT_VIDEO|SDL_INIT_GAMEPAD) && !SDL_Init(SDL_INIT_VIDEO)) { fprintf(stderr,"SDL: %s\n",SDL_GetError()); return 1; }
    SDL_Window *window=SDL_CreateWindow("Monado II - Build and play",1180,780,SDL_WINDOW_RESIZABLE|SDL_WINDOW_HIDDEN);
    if (!window) { fprintf(stderr,"Window: %s\n",SDL_GetError()); SDL_Quit(); return 1; }
    SDL_Renderer *renderer=SDL_CreateRenderer(window,nullptr);
    if (!renderer) renderer=SDL_CreateRenderer(window,"software");
    if (!renderer) { fprintf(stderr,"Renderer: %s\n",SDL_GetError()); SDL_DestroyWindow(window); SDL_Quit(); return 1; }
    SDL_SetRenderVSync(renderer,1);
    IMGUI_CHECKVERSION(); ImGui::CreateContext();
    ImGuiIO &io=ImGui::GetIO(); io.IniFilename=nullptr;
    io.ConfigFlags|=ImGuiConfigFlags_NavEnableGamepad|ImGuiConfigFlags_NavEnableKeyboard;
    float scale=SDL_GetWindowDisplayScale(window); if (scale<=0) scale=1;
    if (!ui::fonts(io,scale)) io.Fonts->AddFontDefault(); ui::style(scale);
    SDL_SetWindowSize(window,(int)(1180*scale),(int)(780*scale));
    SDL_SetWindowMinimumSize(window,(int)(700*scale),(int)(560*scale));
    SDL_SetWindowPosition(window,SDL_WINDOWPOS_CENTERED,SDL_WINDOWPOS_CENTERED);
    SDL_Texture *art=ui::artwork(renderer);
    ImGui_ImplSDL3_InitForSDLRenderer(window,renderer); ImGui_ImplSDLRenderer3_Init(renderer);
    if (!headless) SDL_ShowWindow(window);
    Wizard wizard; wizard.session=session; wizard.details=preview_details;
    const char *home=getenv("HOME"); wizard.set(wizard.output,std::string(home?home:".")+"/Games/Monado-II");
    bool run=true; int frames=0,result=0;
    while(run) {
        wizard.poll(); wizard.apply_dialog();
        if (headless && !frames && preview>=0) wizard.page=preview;
        if (wizard.done || (wizard.close_after_cancel && !wizard.busy())) break;
        SDL_Event event;
        while(SDL_PollEvent(&event)) {
            ImGui_ImplSDL3_ProcessEvent(&event);
            if (event.type==SDL_EVENT_QUIT || (event.type==SDL_EVENT_WINDOW_CLOSE_REQUESTED && event.window.windowID==SDL_GetWindowID(window))) {
                if (wizard.busy()) wizard.close_requested=true; else run=false;
            }
        }
        ImGui_ImplSDLRenderer3_NewFrame(); ImGui_ImplSDL3_NewFrame(); ImGui::NewFrame();
        wizard.draw(window,io.DisplaySize,scale); ImGui::Render();
        SDL_SetRenderDrawColor(renderer,10,20,32,255); SDL_RenderClear(renderer);
        ui::render_art(renderer,art); ImGui_ImplSDLRenderer3_RenderDrawData(ImGui::GetDrawData(),renderer);
        if (headless && ++frames>=headless) {
            if (!screenshot.empty()) { SDL_Surface *surface=SDL_RenderReadPixels(renderer,nullptr); if (!surface || !SDL_SaveBMP(surface,screenshot.c_str())) result=1; if(surface) SDL_DestroySurface(surface); }
            run=false;
        }
        SDL_RenderPresent(renderer);
        if (!headless) SDL_Delay(10);
    }
    ImGui_ImplSDLRenderer3_Shutdown(); ImGui_ImplSDL3_Shutdown(); ImGui::DestroyContext();
    if(art) SDL_DestroyTexture(art); SDL_DestroyRenderer(renderer); SDL_DestroyWindow(window); SDL_Quit();
    return result;
}
