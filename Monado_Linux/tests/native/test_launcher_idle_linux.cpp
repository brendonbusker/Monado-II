// [XCDE] LINUX-126: actual launcher loop, authored children/IPC and SDL dummy only.
// Inject OS presentation/focus facts, never replace the loop or execute game data.
#include <SDL3/SDL.h>
#include <SDL3/SDL_main.h>
#include <sys/resource.h>
#include <cstdio>
#include <cstdlib>
#include "imgui_internal.h"
static bool fixture_poll(SDL_Event *);
static bool fixture_wait(SDL_Event *, Sint32);
static bool fixture_present(SDL_Renderer *);
static bool fixture_vsync(SDL_Renderer *, int);
static SDL_WindowFlags fixture_flags(SDL_Window *);
static SDL_Window *fixture_create(const char *, int, int, SDL_WindowFlags);
static bool fixture_show(SDL_Window *);
static bool fixture_size(SDL_Window *,int,int);
#define SDL_PollEvent fixture_poll
#define SDL_WaitEventTimeout fixture_wait
#define SDL_RenderPresent fixture_present
#define SDL_SetRenderVSync fixture_vsync
#define SDL_GetWindowFlags fixture_flags
#define SDL_CreateWindow fixture_create
#define SDL_ShowWindow fixture_show
#define SDL_SetWindowSize fixture_size
#define main launcher_main_under_test
#include "../../tools/launcher/launcher.cpp"
#undef main
#undef SDL_PollEvent
#undef SDL_WaitEventTimeout
#undef SDL_RenderPresent
#undef SDL_SetRenderVSync
#undef SDL_GetWindowFlags
#undef SDL_CreateWindow
#undef SDL_ShowWindow
#undef SDL_SetWindowSize

#define CHECK(x) do { if (!(x)) { fprintf(stderr,"FAIL %d: %s (errno: %s; launcher: %s; SDL: %s)\n",__LINE__,#x,strerror(errno),launcher_linux::error.c_str(),SDL_GetError()); abort(); } } while (0)
static std::string mode;
static bool baseline, initialized, finished, sent_running, sent_exit, changed_focus, held, detached, released_after_detach;
static Uint64 started, restored_at, first_restored_paint;
static unsigned paints, background_paints, waits, polls, repeats, held_frames;
static unsigned navigation_changes;
static ImGuiID last_navigation;
static int peer = -1, phase;
static int capability[2] = {-1,-1};
static SDL_Window *fixture_window;
static SDL_WindowFlags flags;
static SDL_JoystickID pad_id;
static SDL_Joystick *pad;
static Uint64 monotonic_ns() { timespec t{};CHECK(!clock_gettime(CLOCK_MONOTONIC,&t));return (Uint64)t.tv_sec*1000000000ull+t.tv_nsec; }
static Uint64 elapsed_ms() { return (monotonic_ns()-started)/1000000; }
static void packet(const std::string &text) { CHECK(peer>=0 && send(peer,text.data(),text.size(),MSG_NOSIGNAL)==(ssize_t)text.size()); }
static void broker_start() {
    CHECK(launcher_linux::game_receive("1\tready\tfixture"));
    CHECK(launcher_linux::start_game(g_root));
    CHECK(launcher_linux::game_pid==-1);
    char message[2048]; bool play=false;
    for(ssize_t n;(n=recv(peer,message,sizeof message,MSG_DONTWAIT))>0;)
        play |= std::string(message,(size_t)n)=="1\tplay\t1";
    CHECK(play);
}
static void attach_pad() {
    SDL_VirtualJoystickDesc description; SDL_INIT_INTERFACE(&description);
    description.type=SDL_JOYSTICK_TYPE_GAMEPAD; description.naxes=SDL_GAMEPAD_AXIS_COUNT;
    description.nbuttons=SDL_GAMEPAD_BUTTON_COUNT;
    description.axis_mask=(1u<<SDL_GAMEPAD_AXIS_COUNT)-1u;
    description.button_mask=(1u<<SDL_GAMEPAD_BUTTON_COUNT)-1u;
    description.vendor_id=0xf00d;description.product_id=0x0125;
    description.name="Monado authored idle-loop controller";
    pad_id=SDL_AttachVirtualJoystick(&description); CHECK(pad_id);
    pad=SDL_OpenJoystick(pad_id); CHECK(pad);
    int count=0;SDL_JoystickID *ids=SDL_GetGamepads(&count);
    CHECK(ids && count==1 && ids[0]==pad_id);SDL_free(ids);
    CHECK(SDL_SetJoystickVirtualAxis(pad,SDL_GAMEPAD_AXIS_LEFT_TRIGGER,SDL_JOYSTICK_AXIS_MIN));
    CHECK(SDL_SetJoystickVirtualAxis(pad,SDL_GAMEPAD_AXIS_RIGHT_TRIGGER,SDL_JOYSTICK_AXIS_MIN));
}
static void initialize() {
    initialized=true; started=monotonic_ns();
    flags=mode=="foreground" ? SDL_WINDOW_INPUT_FOCUS : 0;
    if(mode.find("hidden-")==0) flags=SDL_WINDOW_HIDDEN|SDL_WINDOW_MINIMIZED;
    if(mode=="hidden-child" || mode=="background-game") {
        launcher_linux::game_pid=launcher_linux::spawn({"/usr/bin/python3","-I","-B","-c",
            "import pathlib,sys,time; time.sleep(.45); pathlib.Path(sys.argv[1]).write_text('volume = 143\\n'); time.sleep(.1)",path("xcde.ini")},path("logs/authored-child.log"));
        CHECK(launcher_linux::game_pid>0); launcher_linux::game_seen=true;
    } else if(mode=="hidden-precompile-cancel") {
        launcher_linux::precompile_pid=launcher_linux::spawn({"/usr/bin/python3","-I","-B","-c",
            "import signal,sys,time; signal.signal(signal.SIGTERM,lambda *_:sys.exit(130)); print('AUTHORED READY',flush=True); time.sleep(5)"},path("logs/authored-precompile.log"),true);
        CHECK(launcher_linux::precompile_pid>0);
    } else if(mode=="hidden-broker-exit" || mode=="hidden-broker-disconnect") broker_start();
    else if(mode=="hidden-update-ready" || mode=="hidden-update-cancel") {
        launcher_linux::update_last_activity=0;
        CHECK(launcher_linux::update_receive("1\toffer\tauthored-id\t0.0.0\t1\tAuthored update"));
        CHECK(launcher_linux::update_apply());
    } else if(mode=="focus-controller") attach_pad();
}
static bool fixture_poll(SDL_Event *event) {
    ++polls; if(!initialized)initialize();
    Uint64 t=elapsed_ms();
    if((mode=="hidden-broker-exit" || mode=="hidden-broker-disconnect") && t>=100 && !sent_running) {
        packet("1\trunning\t1\tAuthored game running"); sent_running=true;
    }
    if(mode=="hidden-broker-exit" && t>=300 && !sent_exit) {
        FILE *f=fopen(path("xcde.ini").c_str(),"w");CHECK(f);CHECK(fputs("volume = 143\n",f)>=0 && !fclose(f));
        packet("1\texit\t1\t0\tGame closed. Settings are available.");sent_exit=true;
    }
    if(mode=="hidden-broker-disconnect" && t>=250 && peer>=0) {close(peer);peer=-1;}
    if(mode=="hidden-update-ready" && t>=250 && !sent_exit) {packet("1\tready\tAuthored ready");sent_exit=true;}
    if(mode=="hidden-update-cancel" && t>=200 && phase==0) {
        CHECK(launcher_linux::update_snapshot.applying);phase=1;event->type=SDL_EVENT_QUIT;return true;
    }
    if(mode=="hidden-update-cancel" && phase==1) {
        char message[2048];bool cancel=false;
        for(ssize_t n;(n=recv(peer,message,sizeof message,MSG_DONTWAIT))>0;)cancel|=std::string(message,(size_t)n)=="1\tcancel";
        CHECK(cancel);packet("1\tcancelled\tAuthored cancelled");phase=2;
    }
    if(mode=="hidden-precompile-cancel" && t>=200 && !finished) {
        CHECK(launcher_linux::precompile_pid>0);finished=true;event->type=SDL_EVENT_QUIT;return true;
    }
    if(mode=="focus-controller") {
        if(t>=250 && !changed_focus) {
            flags=SDL_WINDOW_INPUT_FOCUS;changed_focus=true;restored_at=SDL_GetTicksNS();
            SDL_Event e{};e.type=SDL_EVENT_WINDOW_FOCUS_GAINED;e.window.windowID=SDL_GetWindowID(fixture_window);CHECK(SDL_PushEvent(&e));
        }
        if(t>=300 && !held) {
            CHECK(SDL_SetJoystickVirtualAxis(pad,SDL_GAMEPAD_AXIS_LEFTY,32767));
            CHECK(SDL_SetJoystickVirtualButton(pad,SDL_GAMEPAD_BUTTON_DPAD_DOWN,true));held=true;
        }
        if(t>=950 && !detached) {SDL_CloseJoystick(pad);pad=nullptr;CHECK(SDL_DetachVirtualJoystick(pad_id));detached=true;}
    }
    Uint64 end=mode=="focus-controller" ? 1150 : mode=="foreground" ? 650 : 750;
    if(t>=end && !finished) {
        if(mode=="hidden-child" || mode=="background-game" || mode=="hidden-broker-exit")
            CHECK(!launcher_linux::game_pid && g.volume==143 && !launcher_linux::last_result);
        if(mode=="hidden-broker-disconnect")
            CHECK(launcher_linux::game_pid==-1 && launcher_linux::game_fd<0 && launcher_linux::activity_busy());
        if(mode=="hidden-update-cancel")
            CHECK(!launcher_linux::update_snapshot.applying && launcher_linux::update_snapshot.phase=="cancelled");
        finished=true;event->type=SDL_EVENT_QUIT;return true;
    }
    return SDL_PollEvent(event);
}
static bool fixture_wait(SDL_Event *event,Sint32 timeout) {
    CHECK(timeout>0 && timeout<=50);++waits;return SDL_WaitEventTimeout(event,timeout);
}
static bool fixture_present(SDL_Renderer *renderer) {
    ++paints;if(!(flags&SDL_WINDOW_INPUT_FOCUS))++background_paints;
    if(changed_focus && !first_restored_paint)first_restored_paint=SDL_GetTicksNS();
    if(mode=="focus-controller" && held && !detached && ImGui::IsKeyDown(ImGuiKey_GamepadLStickDown)) {
        ++held_frames;repeats+=(unsigned)ImGui::GetKeyPressedAmount(ImGuiKey_GamepadDpadDown,.2f,.05f);
        ImGuiID selected=ImGui::GetCurrentContext()->NavId;
        if(selected && selected!=last_navigation){++navigation_changes;last_navigation=selected;}
    }
    if(mode=="focus-controller" && detached && !ImGui::IsKeyDown(ImGuiKey_GamepadDpadDown) && !ImGui::IsKeyDown(ImGuiKey_GamepadLStickDown))released_after_detach=true;
    return SDL_RenderPresent(renderer);
}
static bool fixture_vsync(SDL_Renderer *,int) { SDL_SetError("Authored unsupported VSync fixture");return false; }
static SDL_WindowFlags fixture_flags(SDL_Window *) { return flags; }
static SDL_Window *fixture_create(const char *title,int w,int h,SDL_WindowFlags window_flags) {
    fixture_window=SDL_CreateWindow(title,w,h,window_flags|SDL_WINDOW_HIDDEN);return fixture_window;
}
static bool fixture_show(SDL_Window *) { return true; }
static bool fixture_size(SDL_Window *window,int width,int height) {
    // A supported compact surface makes software painting fast enough to test
    // the independent 60 Hz ceiling rather than merely a slow renderer's limit.
    if(mode=="foreground" || mode=="focus-controller") {width=640;height=480;}
    return SDL_SetWindowSize(window,width,height);
}
static double cpu_seconds(const rusage &r) {return r.ru_utime.tv_sec+r.ru_utime.tv_usec/1e6+r.ru_stime.tv_sec+r.ru_stime.tv_usec/1e6;}
int main(int argc,char **argv) {
    CHECK(argc>2);mode=argv[1];baseline=getenv("MONADO_IDLE_BASELINE")!=nullptr;
    // This fixture must not open or consume a person's attached controller.
    // Only the authored virtual VID/PID is admitted to ImGui's AutoFirst list.
    CHECK(SDL_SetHint(SDL_HINT_JOYSTICK_HIDAPI,"0"));
    CHECK(SDL_SetHint(SDL_HINT_GAMECONTROLLER_IGNORE_DEVICES_EXCEPT,"0xf00d/0x0125"));
    CHECK(SDL_SetHint(SDL_HINT_JOYSTICK_ALLOW_BACKGROUND_EVENTS,"1"));
    // Match real inherited host capabilities: create descriptors before the
    // production launcher installs its state-write guard.
    if(mode.find("hidden-broker-")==0 || mode.find("hidden-update-")==0) {
        CHECK(!socketpair(AF_UNIX,SOCK_SEQPACKET|SOCK_CLOEXEC|SOCK_NONBLOCK,0,capability));
        peer=capability[1];
        if(mode.find("hidden-broker-")==0)CHECK(launcher_linux::game_adopt_fd(capability[0]));
        else CHECK(launcher_linux::update_adopt_fd(capability[0]));
    }
    rusage before{},after{};CHECK(!getrusage(RUSAGE_SELF,&before));
    int result=launcher_main_under_test(argc-1,argv+1);CHECK(!getrusage(RUSAGE_SELF,&after));
    if(mode=="hidden-update-ready")CHECK(result==75 && sent_exit);
    else CHECK(!result && finished);
    if(mode=="hidden-precompile-cancel")CHECK(g_pc_quit && !launcher_linux::precompile_pid && launcher_linux::precompile_cancelling);
    if(!baseline) {
        // A slow software foreground paint can already exceed the 60 Hz budget.
        if(mode!="foreground")CHECK(waits>0);
        if(mode.find("hidden-")==0)CHECK(!paints);
        if(mode=="background-game")CHECK(background_paints<=5);
        if(mode=="foreground")CHECK(paints>=15 && paints<=45);
        if(mode=="focus-controller") {
            fprintf(stderr,"controller observation: paints=%u held_frames=%u repeats=%u widget_changes=%u detached=%d restore_ms=%.2f\n",paints,held_frames,repeats,navigation_changes,detached,(first_restored_paint-restored_at)/1e6);
            CHECK(first_restored_paint>=restored_at && first_restored_paint-restored_at<100000000);
            CHECK(held_frames>=15 && repeats>=5 && navigation_changes>=2 && detached && released_after_detach && paints<=80);
        }
    }
    if(peer>=0)close(peer);
    CHECK(waitpid(-1,nullptr,WNOHANG)==-1 && errno==ECHILD);
    printf("launcher idle: PASS mode=%s baseline=%d paints=%u background_paints=%u waits=%u polls=%u held_frames=%u repeats=%u elapsed_ms=%llu cpu_seconds=%.6f\n",
        mode.c_str(),baseline,paints,background_paints,waits,polls,held_frames,repeats,(unsigned long long)elapsed_ms(),cpu_seconds(after)-cpu_seconds(before));
    return 0;
}
