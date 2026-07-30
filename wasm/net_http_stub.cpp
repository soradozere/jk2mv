// WASM build: HTTP downloads/master-server communication (mongoose-based in the
// real net_http.cpp) are irrelevant to local demo playback and pull in a whole
// embedded HTTP server library we don't want to port. Stub out the symbols the
// rest of the engine calls so it links; none of these paths get exercised when
// playing a demo from local preloaded assets.
#include "../src/qcommon/q_shared.h"
#include "../src/qcommon/qcommon.h"

void NET_HTTP_AllowClient(int clientNum, netadr_t addr) {}
void NET_HTTP_DenyClient(int clientNum) {}
int NET_HTTP_StartServer(int port) { return 0; }
void NET_HTTP_StopServer() {}
dlHandle_t NET_HTTP_StartDownload(const char *url, const char *toPath, dl_ended_callback ended_callback, dl_status_callback status_callback) {
	if (ended_callback) {
		ended_callback(0, qfalse, "HTTP downloads are not available in the WASM build");
	}
	return 0;
}
void NET_HTTP_StopDownload(dlHandle_t handle) {}
void NET_HTTP_Init() {}
void NET_HTTP_ProcessEvents() {}
void NET_HTTP_Shutdown() {}
