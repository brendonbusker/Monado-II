// Authored flat JSON IPC contract fixtures. No SDL, game files or game code.
#include "json.h"
#include <cassert>
#include <string>

namespace json = builder_json;
static bool rejects(const std::string &s) {
    try { json::parse(s); return false; }
    catch (const std::runtime_error &) { return true; }
}

int main(int argc, char **argv) {
    if (argc != 2) return 2;
    std::string group = argv[1];
    if (group == "getters") {
        auto object = json::parse(" {\"schema\":1,\"phase\":\"ready\",\"progress\":0.3e+0,\"can_open\":true,\"optional\":null} \n");
        assert(json::number(object,"schema") == 1);
        assert(json::text(object,"phase") == "ready");
        assert(json::number(object,"progress") == .3);
        assert(json::boolean(object,"can_open"));
        assert(!json::boolean(object,"phase"));
        assert(json::number(object,"phase",7) == 7);
        assert(json::text(object,"schema","wrong type") == "wrong type");
        assert(json::text(object,"optional","empty") == "empty");
        assert(json::text(object,"absent","missing") == "missing");
        assert(json::number(object,"absent",42) == 42);
        assert(!json::boolean(object,"absent"));
        assert(json::parse("{}").empty());
    } else if (group == "paths") {
        const std::string samples[] = {
            "/authored/player/My Games/Monado II/game_files",
            "/tmp/\"quoted\"/\\backslash/parenthesized (folder)",
            "/tmp/caf\xc3\xa9/\xe6\xb8\xb8\xe6\x88\x8f",
            "line\nfeed\twith\rcontrols\b\f\x1b",
            "", "/", "literal $(not-a-command) and `not-a-command`"
        };
        for (const auto &sample : samples) {
            std::string document = "{\"path\":" + json::quote(sample) + "}";
            assert(json::text(json::parse(document),"path") == sample);
        }
        assert(json::text(json::parse("{\"path\":\"\\/tmp\\/folder\"}"),"path") == "/tmp/folder");
    } else if (group == "unicode") {
        assert(json::text(json::parse("{\"text\":\"\\u00e9\\uD83D\\uDE80\"}"),"text") == "\xc3\xa9\xf0\x9f\x9a\x80");
        assert(json::text(json::parse("{\"text\":\"\\u6e38\\u620f\"}"),"text") == "\xe6\xb8\xb8\xe6\x88\x8f");
        for (const auto *bad : {"{\"x\":\"\\uD800\"}", "{\"x\":\"\\uDC00\"}",
                                "{\"x\":\"\\uD800\\u0020\"}", "{\"x\":\"\\u0000\"}",
                                "{\"x\":\"\\u00xz\"}"}) assert(rejects(bad));
    } else if (group == "invalid") {
        for (const auto *bad : {"", "[]", "{", "{\"x\":1,}", "{\"x\":01}",
                                "{\"x\":.5}", "{\"x\":1.}", "{\"x\":1e}",
                                "{\"x\":1e9999}", "{\"x\":NaN}", "{\"x\":Infinity}",
                                "{\"x\":{}}", "{\"x\":[]}", "{} trailing",
                                "{\"x\":true,\"x\":false}", "{\"schema\":1,\"\\u0073chema\":1}",
                                "{\"x\":\"\\z\"}", "{\"x\":\"line\nfeed\"}",
                                "{\"x\":truefalse}"}) assert(rejects(bad));
        std::string control = "{\"x\":\"before";
        control += char(1); control += "after\"}";
        assert(rejects(control));
    } else if (group == "truncated") {
        const std::string document = "{\"phase\":\"ready\",\"path\":\"/tmp/\\u00e9\",\"schema\":1}";
        for (size_t size = 0; size < document.size(); ++size) assert(rejects(document.substr(0,size)));
        assert(json::text(json::parse(document),"phase") == "ready");
    } else if (group == "bounds") {
        assert(rejects(std::string(1024*1024+1,' ')));
        std::string many="{";
        for (int i=0;i<65;++i) { if(i) many+=","; many+=json::quote(std::to_string(i))+":1"; }
        assert(rejects(many+"}"));
        std::string payload(32000,'x');
        assert(json::text(json::parse("{\"detail\":"+json::quote(payload)+"}"),"detail") == payload);
    } else return 2;
    return 0;
}
