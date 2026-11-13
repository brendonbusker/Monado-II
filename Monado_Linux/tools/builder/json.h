// Monado II builder's bounded, flat JSON IPC. Authored code under the MIT license.
#pragma once
#include <cmath>
#include <cstdlib>
#include <map>
#include <stdexcept>
#include <string>

namespace builder_json {
struct Value {
    enum Kind { String, Number, Boolean, Null } kind = Null;
    std::string text;
    double number = 0;
    bool boolean = false;
};
using Object = std::map<std::string, Value>;
struct Parser {
    const std::string &data;
    size_t pos = 0;
    explicit Parser(const std::string &s) : data(s) {}
    [[noreturn]] void fail() const { throw std::runtime_error("Invalid builder status JSON"); }
    void ws() { while (pos < data.size() && (data[pos] == ' ' || data[pos] == '\r' || data[pos] == '\n' || data[pos] == '\t')) ++pos; }
    char take() { if (pos >= data.size()) fail(); return data[pos++]; }
    unsigned hex4() {
        unsigned result = 0;
        for (int i = 0; i < 4; ++i) {
            char c = take(); unsigned digit;
            if (c >= '0' && c <= '9') digit = c - '0';
            else if (c >= 'a' && c <= 'f') digit = c - 'a' + 10;
            else if (c >= 'A' && c <= 'F') digit = c - 'A' + 10;
            else { fail(); digit = 0; }
            result = result * 16 + digit;
        }
        return result;
    }
    void utf8(std::string &out, unsigned c) {
        if (!c || c > 0x10ffff || (c >= 0xd800 && c <= 0xdfff)) fail();
        if (c < 0x80) out += char(c);
        else if (c < 0x800) { out += char(0xc0 | (c >> 6)); out += char(0x80 | (c & 63)); }
        else if (c < 0x10000) { out += char(0xe0 | (c >> 12)); out += char(0x80 | ((c >> 6) & 63)); out += char(0x80 | (c & 63)); }
        else { out += char(0xf0 | (c >> 18)); out += char(0x80 | ((c >> 12) & 63)); out += char(0x80 | ((c >> 6) & 63)); out += char(0x80 | (c & 63)); }
    }
    std::string string() {
        if (take() != '"') fail();
        std::string out;
        for (;;) {
            unsigned char c = (unsigned char)take();
            if (c == '"') return out;
            if (c < 32) fail();
            if (c != '\\') { out += char(c); continue; }
            c = (unsigned char)take();
            if (c == '"' || c == '\\' || c == '/') out += char(c);
            else if (c == 'b') out += '\b'; else if (c == 'f') out += '\f';
            else if (c == 'n') out += '\n'; else if (c == 'r') out += '\r'; else if (c == 't') out += '\t';
            else if (c == 'u') {
                unsigned code = hex4();
                if (code >= 0xd800 && code <= 0xdbff) {
                    if (take() != '\\' || take() != 'u') fail();
                    unsigned low = hex4(); if (low < 0xdc00 || low > 0xdfff) fail();
                    code = 0x10000 + ((code - 0xd800) << 10) + low - 0xdc00;
                }
                utf8(out, code);
            } else fail();
        }
    }
    Value value() {
        ws(); if (pos == data.size()) fail(); Value v;
        if (data[pos] == '"') { v.kind = Value::String; v.text = string(); return v; }
        for (const char *word : {"true", "false", "null"}) {
            std::string s = word;
            if (data.compare(pos, s.size(), s) == 0) {
                pos += s.size(); v.kind = s == "null" ? Value::Null : Value::Boolean;
                v.boolean = s == "true"; return v;
            }
        }
        size_t start = pos;
        if (data[pos] == '-') ++pos;
        if (pos == data.size()) fail();
        if (data[pos] == '0') ++pos;
        else { if (data[pos] < '1' || data[pos] > '9') fail(); while (pos < data.size() && data[pos] >= '0' && data[pos] <= '9') ++pos; }
        if (pos < data.size() && data[pos] == '.') {
            ++pos; size_t digits = pos;
            while (pos < data.size() && data[pos] >= '0' && data[pos] <= '9') ++pos;
            if (pos == digits) fail();
        }
        if (pos < data.size() && (data[pos] == 'e' || data[pos] == 'E')) {
            ++pos; if (pos < data.size() && (data[pos] == '+' || data[pos] == '-')) ++pos;
            size_t digits = pos; while (pos < data.size() && data[pos] >= '0' && data[pos] <= '9') ++pos;
            if (pos == digits) fail();
        }
        std::string number = data.substr(start, pos - start);
        v.number = std::strtod(number.c_str(), nullptr); if (!std::isfinite(v.number)) fail();
        v.kind = Value::Number; return v;
    }
    Object object() {
        if (data.size() > 1024 * 1024) fail();
        Object out; ws(); if (take() != '{') fail(); ws();
        if (pos < data.size() && data[pos] == '}') ++pos;
        else for (;;) {
            ws(); std::string key = string(); ws(); if (take() != ':') fail();
            if (out.size() >= 64 || out.count(key)) fail();
            out.emplace(key, value()); ws(); char c = take(); if (c == '}') break; if (c != ',') fail();
        }
        ws(); if (pos != data.size()) fail(); return out;
    }
};
inline Object parse(const std::string &data) { return Parser(data).object(); }
inline std::string text(const Object &o, const std::string &key, const std::string &fallback = "") {
    auto i = o.find(key); return i != o.end() && i->second.kind == Value::String ? i->second.text : fallback;
}
inline double number(const Object &o, const std::string &key, double fallback = 0) {
    auto i = o.find(key); return i != o.end() && i->second.kind == Value::Number ? i->second.number : fallback;
}
inline bool boolean(const Object &o, const std::string &key) {
    auto i = o.find(key); return i != o.end() && i->second.kind == Value::Boolean && i->second.boolean;
}
inline std::string quote(const std::string &s) {
    std::string out = "\"";
    for (unsigned char c : s) {
        if (c == '"' || c == '\\') { out += '\\'; out += char(c); }
        else if (c < 32) { static const char *hex = "0123456789abcdef"; out += "\\u00"; out += hex[c >> 4]; out += hex[c & 15]; }
        else out += char(c);
    }
    return out + '"';
}
} // namespace builder_json
