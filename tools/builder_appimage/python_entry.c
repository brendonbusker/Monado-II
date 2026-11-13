/* Monado II: restore only this private Python runtime's library directory.
 * Preserve argv[0]: CPython uses the virtual-environment entry path to locate
 * pyvenv.cfg. /proc/self/exe identifies this immutable runtime's real wrapper.
 * No shell, PATH lookup, system modification or game code is involved.
 */
#define _GNU_SOURCE
#include <errno.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char self[PATH_MAX], binary[PATH_MAX], libraries[PATH_MAX];
    ssize_t n = readlink("/proc/self/exe", self, sizeof(self) - 1);
    if (n <= 0 || n >= (ssize_t)sizeof(self) - 1) {
        fputs("Monado II: cannot locate private Python entry point\n", stderr);
        return 126;
    }
    self[n] = 0;
    char *slash = strrchr(self, '/');
    if (!slash) return 126;
    *slash = 0;
    if (snprintf(binary, sizeof(binary), "%s/python3.14.real", self) >= (int)sizeof(binary)) return 126;
    slash = strrchr(self, '/');
    if (!slash) return 126;
    *slash = 0;
    if (snprintf(libraries, sizeof(libraries), "%s/lib", self) >= (int)sizeof(libraries)) return 126;
    unsetenv("LD_PRELOAD");
    unsetenv("PYTHONHOME");
    unsetenv("PYTHONPATH");
    if (setenv("LD_LIBRARY_PATH", libraries, 1) != 0) return 126;
    /* The private OpenSSL build must use the host's trust store on Fedora as
     * well as Debian/Ubuntu. Clean build subprocess environments discard TLS
     * overrides, so select only an existing standard system certificate file.
     */
    const char *stores[] = {"/etc/ssl/certs/ca-certificates.crt",
        "/etc/pki/tls/certs/ca-bundle.crt", "/etc/ssl/cert.pem",
        "/etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem", NULL};
    for (int i = 0; stores[i]; i++) {
        struct stat st;
        if (stat(stores[i], &st) == 0 && S_ISREG(st.st_mode) && access(stores[i], R_OK) == 0) {
            if (setenv("SSL_CERT_FILE", stores[i], 1) != 0) return 126;
            break;
        }
    }
    /* Interpreter flags are not inherited by child interpreters. Some build
     * tools start Python with -E/-I, which also ignore bytecode environment
     * controls. Keep this manifest-bound runtime immutable by always supplying
     * -B on the real interpreter's argv, while retaining the venv's argv[0].
     */
    char **arguments = calloc((size_t)argc + 2, sizeof(*arguments));
    if (!arguments) {
        fputs("Monado II: cannot allocate private Python arguments\n", stderr);
        return 126;
    }
    arguments[0] = argv[0];
    arguments[1] = "-B";
    for (int i = 1; i < argc; ++i) arguments[i + 1] = argv[i];
    execv(binary, arguments);
    free(arguments);
    fprintf(stderr, "Monado II: cannot start private Python (%s)\n", strerror(errno));
    return 126;
}
