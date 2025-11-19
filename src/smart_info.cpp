// simple C++ SMART info viewer (minimal dependency)
// Build with: cmake .. && make

#include <algorithm>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <filesystem>
#include <iostream>
#include <map>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <vector>

using namespace std;

static string exec_capture(const string &cmd) {
    string result;
    FILE *pipe = popen(cmd.c_str(), "r");
    if (!pipe) return result;
    char buffer[4096];
    while (fgets(buffer, sizeof(buffer), pipe)) {
        result += buffer;
    }
    pclose(pipe);
    return result;
}

static string find_smartctl() {
    string p = exec_capture("command -v smartctl 2>/dev/null");
    if (!p.empty()) {
        // trim
        while (!p.empty() && (p.back()=='\n' || p.back()=='\r' || isspace((unsigned char)p.back()))) p.pop_back();
        return p;
    }
    return string();
}

static vector<string> list_devices(const string &smartctl) {
    string cmd = smartctl + " --scan";
    string out = exec_capture(cmd);
    vector<string> devs;
    istringstream ss(out);
    string line;
    while (getline(ss, line)) {
        if (line.empty()) continue;
        // first token is device
        istringstream ls(line);
        string token; ls >> token;
        if (!token.empty()) devs.push_back(token);
    }
    return devs;
}

static string run_smartctl(const string &smartctl, const string &device) {
    string cmd = smartctl + " -a " + device + " 2>&1";
    return exec_capture(cmd);
}

static string json_escape(const string &s) {
    string out;
    for (unsigned char c: s) {
        switch (c) {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\b': out += "\\b"; break;
            case '\f': out += "\\f"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default:
                if (c < 0x20) {
                    char buf[8];
                    snprintf(buf, sizeof(buf), "\\u%04x", c);
                    out += buf;
                } else out += c;
        }
    }
    return out;
}

struct Field { string raw; string unit; bool has_num; long long num; };

static map<string, Field> parse_nvme_section(const vector<string> &lines) {
    map<string, Field> out;
    regex bracket_regex("\\\[(.*)\\\]");
    regex num_unit_regex("^\\s*([-+]?[0-9,]+)(?:\\s*([A-Za-z%\.]+))?");
    for (auto &l: lines) {
        auto p = l.find(':');
        if (p==string::npos) continue;
        string key = l.substr(0,p);
        string val = l.substr(p+1);
        // trim
        auto trim = [](string &s){
            while (!s.empty() && isspace((unsigned char)s.front())) s.erase(s.begin());
            while (!s.empty() && isspace((unsigned char)s.back())) s.pop_back();
        };
        trim(key); trim(val);
        string k = key;
        // normalize key
        transform(k.begin(), k.end(), k.begin(), [](unsigned char c){ return tolower(c==' '?'_':c); });
        // replace spaces with underscores
        for (char &c: k) if (c==' ') c='_';
        Field f; f.raw = val; f.has_num=false; f.num=0; f.unit="";
        smatch m;
        if (regex_search(val, m, bracket_regex)) {
            // find leading number
            if (regex_search(val, m, num_unit_regex)) {
                string num = m[1];
                num.erase(remove(num.begin(), num.end(), ','), num.end());
                try { f.num = stoll(num); f.has_num=true; } catch(...) { f.has_num=false; }
            }
            f.unit = m[1];
        } else {
            if (regex_search(val, m, num_unit_regex)) {
                string num = m[1]; num.erase(remove(num.begin(), num.end(), ','), num.end());
                try { f.num = stoll(num); f.has_num=true; } catch(...) { f.has_num=false; }
                if (m.size()>2) f.unit = m[2];
            }
        }
        out[k] = f;
    }
    return out;
}

static string build_json_from_parsed(const map<string,string> &kv, const map<string,Field> &nvme, bool include_raw) {
    ostringstream js;
    js << "{";
    bool first=true;
    auto add_comma=[&](){ if (!first) js<<","; first=false; };
    for (auto &p: kv) {
        add_comma(); js << "\n  \"" << json_escape(p.first) << "\": \"" << json_escape(p.second) << "\"";
    }
    if (!nvme.empty()) {
        add_comma(); js << "\n  \"nvme_health\": {";
        bool f2=true;
        for (auto &n: nvme) {
            if (!f2) js<<","; f2=false;
            js << "\n    \"" << json_escape(n.first) << "\": {";
            js << "\n      \"raw\": \"" << json_escape(n.second.raw) << "\"";
            if (n.second.has_num) js << ",\n      \"value\": " << n.second.num;
            if (!n.second.unit.empty()) js << ",\n      \"unit\": \"" << json_escape(n.second.unit) << "\"";
            js << "\n    }";
        }
        js << "\n  }";
    }
    if (include_raw) {
        add_comma(); js << "\n  \"raw\": \"REDACTED_RAW_NOT_INCL_IF_NOT_REQUESTED\"";
    }
    js << "\n}\n";
    return js.str();
}

int main(int argc, char **argv) {
    bool list_mode=false; string device=""; bool json_out=false; bool include_raw=false;
    for (int i=1;i<argc;i++){
        string a=argv[i];
        if (a=="--list") list_mode=true;
        else if (a=="--json") json_out=true;
        else if (a=="--include-raw") include_raw=true;
        else if (a=="--device" && i+1<argc) { device = argv[++i]; }
        else if (a=="-h"||a=="--help") { cout<<"Usage: smart_info [--list] [--device /dev/sda] [--json] [--include-raw]\n"; return 0; }
    }

    string smartctl = find_smartctl();
    if (smartctl.empty()) {
        cerr<<"smartctl not found. Install smartmontools."<<endl;
        return 2;
    }

    if (list_mode) {
        auto devs = list_devices(smartctl);
        if (json_out) {
            cout<<"{"<<"\n  \"devices\": [";
            for (size_t i=0;i<devs.size();++i) {
                if (i) cout<<",";
                cout<<"\n    \""<<json_escape(devs[i])<<"\"";
            }
            cout<<"\n  ]\n}\n";
        } else {
            for (auto &d: devs) cout<<d<<"\n";
        }
        return 0;
    }

    if (device.empty()) {
        cerr<<"Please specify --device or --list"<<endl;
        return 2;
    }

    string out = run_smartctl(smartctl, device);
    // parse top-level fields and nvme
    map<string,string> kv;
    vector<string> nvme_lines;
    bool in_nvme=false;
    istringstream ss(out);
    string line;
    while (getline(ss,line)) {
        string t=line;
        // trim
        auto ltrim=[&](string &s){ while (!s.empty() && isspace((unsigned char)s.front())) s.erase(s.begin()); };
        auto rtrim=[&](string &s){ while (!s.empty() && isspace((unsigned char)s.back())) s.pop_back(); };
        ltrim(t); rtrim(t);
        if (t.empty()) {
            if (in_nvme) {
                // keep going - we end nvme when next section starts
            }
            continue;
        }
        if (t.rfind("Device Model:",0)==0 || t.rfind("Model Number:",0)==0) {
            auto p = t.find(':'); kv["model"] = t.substr(p+1);
            rtrim(kv["model"]);
            ltrim(kv["model"]);
        } else if (t.rfind("Serial Number:",0)==0) {
            auto p = t.find(':'); kv["serial"] = t.substr(p+1); rtrim(kv["serial"]); ltrim(kv["serial"]);
        } else if (t.rfind("Firmware Version:",0)==0) {
            auto p = t.find(':'); kv["firmware"] = t.substr(p+1); rtrim(kv["firmware"]); ltrim(kv["firmware"]);
        } else if (t.rfind("SMART/Health Information",0)==0) {
            in_nvme = true; continue;
        } else if (in_nvme) {
            if (t.rfind("Error Information",0)==0 || t.rfind("Self-test Log",0)==0 || t.rfind("===",0)==0) {
                in_nvme = false;
            } else {
                nvme_lines.push_back(t);
            }
        }
    }

    auto nvme = parse_nvme_section(nvme_lines);
    if (json_out) {
        cout << build_json_from_parsed(kv, nvme, include_raw);
    } else {
        cout << "Device: "<<device<<"\n";
        cout << "Model: "<< (kv.count("model")?kv["model"]:"n/a") <<"\n";
        cout << "Serial: "<< (kv.count("serial")?kv["serial"]:"n/a") <<"\n";
        cout << "Firmware: "<< (kv.count("firmware")?kv["firmware"]:"n/a") <<"\n";
        if (!nvme.empty()) {
            cout<<"\nNVMe SMART/Health:\n";
            for (auto &n: nvme) {
                cout<<n.first<<": "<<n.second.raw<<"\n";
            }
        }
    }

    return 0;
}
