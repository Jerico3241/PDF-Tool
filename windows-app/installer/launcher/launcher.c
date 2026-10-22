/*
 * Novadesk – Startprogramm (PDF-Tool.exe im Programmordner).
 *
 * Startet die eingebettete Python-Laufzeit mit der App:
 *     <Programmordner>\runtime\pythonw.exe -s -OO "<Programmordner>\app\start.py" <Argumente>
 * Die Argumente (z. B. die PDF bei »Öffnen mit«) werden unverändert weitergegeben.
 *
 * Warum ein eigenes Programm: Windows zeigt in »Öffnen mit«, bei den Standard-Apps und in der
 * Taskleiste das Symbol und den Namen der gestarteten EXE. Mit pythonw.exe erschiene dort Python.
 * Diese EXE trägt Symbol und Versionsangaben von Novadesk und endet, sobald die App die übergebenen Dateien
 * gesichert hat (siehe unten).
 * Die App verlässt dabei den Job des aufrufenden Programms (siehe unten).
 *
 * Öffnen einer PDF über die Dateizuordnung (seit 4.0.0-beta.4): Die ProgID »PDFTool.Dokument« trägt DelegateExecute
 * mit der Klasse CLSID_PDFTOOL_OPEN. Windows startet diese EXE dann selbst als COM-Server (»-Embedding«, über den
 * COM-Dienst – nicht als Kindprozess des Aufrufers) und übergibt die Dateien über IExecuteCommand. Das ist der
 * reguläre Weg der Windows-Shell für Verben (wie bei Store-Apps); Outlook darf je nach Firmenregel (Defender:
 * »untergeordnete Prozesse von Office-Kommunikationsanwendungen blockieren«) keine Programme direkt starten.
 */
#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define COBJMACROS
#include <windows.h>
#include <objbase.h>
#include <shobjidl.h>
#include <stddef.h>
#include <stdio.h>
#include <wchar.h>

#define START_WAIT_MS 15000
#define SERVER_IDLE_MS 60000
#define MAX_ARGUMENTS 32768

/* {61E62B6E-0FE6-46A2-8AF1-BD670901BF3B} – auch in installer/PDF-Tool.iss (OpenClsid) */
static const CLSID CLSID_PDFTOOL_OPEN = { 0x61e62b6e, 0x0fe6, 0x46a2, { 0x8a, 0xf1, 0xbd, 0x67, 0x09, 0x01, 0xbf, 0x3b } };

static void fail(const wchar_t *text)
{
    MessageBoxW(NULL, text, L"Novadesk", MB_OK | MB_ICONERROR);
}

/* App starten: runtime\pythonw.exe -s -OO app\start.py <arguments>; wartet wie unten beschrieben. */
static int run_app(const wchar_t *arguments, int show, const wchar_t *activation)
{
    static wchar_t folder[32768];
    DWORD length = GetModuleFileNameW(NULL, folder, (DWORD)(sizeof(folder) / sizeof(folder[0])));
    if (length == 0 || length >= sizeof(folder) / sizeof(folder[0])) {
        fail(L"Novadesk konnte seinen Programmordner nicht bestimmen.");
        return 1;
    }
    wchar_t *slash = wcsrchr(folder, L'\\');
    if (slash == NULL) {
        fail(L"Novadesk konnte seinen Programmordner nicht bestimmen.");
        return 1;
    }
    *slash = L'\0';

    size_t size = wcslen(folder) * 3 + wcslen(arguments) + 64;
    wchar_t *python = HeapAlloc(GetProcessHeap(), 0, size * sizeof(wchar_t));
    wchar_t *workdir = HeapAlloc(GetProcessHeap(), 0, size * sizeof(wchar_t));
    wchar_t *line = HeapAlloc(GetProcessHeap(), 0, size * sizeof(wchar_t));
    if (python == NULL || workdir == NULL || line == NULL) {
        fail(L"Novadesk konnte nicht gestartet werden (zu wenig Arbeitsspeicher).");
        return 1;
    }
    swprintf(python, size, L"%ls\\runtime\\pythonw.exe", folder);
    swprintf(workdir, size, L"%ls\\app", folder);
    swprintf(line, size, L"\"%ls\" -s -OO \"%ls\\start.py\"%ls%ls", python, workdir, arguments[0] ? L" " : L"", arguments);
    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES) {
        fail(L"Novadesk ist unvollständig installiert (runtime\\pythonw.exe fehlt).\n\nBitte das Setup erneut ausführen.");
        return 1;
    }

    STARTUPINFOW startup;
    PROCESS_INFORMATION process;
    ZeroMemory(&startup, sizeof(startup));
    ZeroMemory(&process, sizeof(process));
    startup.cb = sizeof(startup);
    startup.dwFlags = STARTF_USESHOWWINDOW;
    startup.wShowWindow = (WORD)show;
    /*
     * Die App läuft unabhängig vom aufrufenden Programm: Programme wie Hottgenroth »Kaufmann« starten den
     * PDF-Betrachter in einem eigenen Job und halten eine PDF für »noch geöffnet«, solange darin ein Prozess
     * läuft – mit der weiterlaufenden App ließe sich dann keine zweite PDF öffnen. Erlaubt der Job das
     * Verlassen nicht, startet die App wie bisher in ihm.
     */
    /*
     * Outlook löscht seine Kopie eines Anhangs, sobald das gestartete Programm (und sein Job) endet. Dieses
     * Startprogramm wartet deshalb, bis der gestartete Prozess endet (Übergabe an die schon laufende App erledigt)
     * oder – startet die App selbst – bis start.py dieses Ereignis setzt, höchstens START_WAIT_MS.
     */
    wchar_t event_name[64];
    swprintf(event_name, 64, L"Local\\PDFTool-Start-%lu", GetCurrentProcessId());
    HANDLE ready = CreateEventW(NULL, TRUE, FALSE, event_name);
    if (ready != NULL) {
        SetEnvironmentVariableW(L"PDFTOOL_START_EVENT", event_name);
    }
    SetEnvironmentVariableW(L"PDFTOOL_ACTIVATION", activation);  /* fürs Übergabe-Protokoll: »direkt« oder »COM« */
    BOOL started = CreateProcessW(python, line, NULL, NULL, FALSE, CREATE_BREAKAWAY_FROM_JOB, NULL, workdir, &startup, &process);
    if (!started && GetLastError() == ERROR_ACCESS_DENIED) {
        started = CreateProcessW(python, line, NULL, NULL, FALSE, 0, NULL, workdir, &startup, &process);
    }
    if (!started) {
        if (ready != NULL) {
            CloseHandle(ready);
        }
        wchar_t text[256];
        swprintf(text, 256, L"Novadesk konnte nicht gestartet werden (Fehler %lu).", GetLastError());
        fail(text);
        return 1;
    }
    /* Das Fenster der App darf in den Vordergrund (dieses Programm wurde vom Benutzer gestartet). */
    AllowSetForegroundWindow(process.dwProcessId);
    CloseHandle(process.hThread);
    if (ready != NULL) {
        HANDLE waits[2] = { process.hProcess, ready };
        WaitForMultipleObjects(2, waits, FALSE, START_WAIT_MS);
        CloseHandle(ready);
    }
    CloseHandle(process.hProcess);
    return 0;
}


/* COM-Server: IExecuteCommand + IObjectWithSelection ------------------------------------------------------------- */

typedef struct Command {
    IExecuteCommand execute;
    IObjectWithSelection selection;
    LONG refs;
    IShellItemArray *items;
    int show;
} Command;

static LONG g_objects = 0;
static BOOL g_done = FALSE;

#define COMMAND_FROM_SELECTION(p) ((Command *)((char *)(p) - offsetof(Command, selection)))

static void quit_when_idle(void)
{
    if (g_done && g_objects == 0) {
        PostQuitMessage(0);
    }
}

static HRESULT STDMETHODCALLTYPE command_query(IExecuteCommand *self, REFIID riid, void **out)
{
    Command *command = (Command *)self;
    if (out == NULL) {
        return E_POINTER;
    }
    if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IExecuteCommand)) {
        *out = &command->execute;
    } else if (IsEqualIID(riid, &IID_IObjectWithSelection)) {
        *out = &command->selection;
    } else {
        *out = NULL;
        return E_NOINTERFACE;
    }
    InterlockedIncrement(&command->refs);
    return S_OK;
}

static ULONG STDMETHODCALLTYPE command_add_ref(IExecuteCommand *self)
{
    return (ULONG)InterlockedIncrement(&((Command *)self)->refs);
}

static ULONG STDMETHODCALLTYPE command_release(IExecuteCommand *self)
{
    Command *command = (Command *)self;
    LONG refs = InterlockedDecrement(&command->refs);
    if (refs == 0) {
        if (command->items != NULL) {
            IShellItemArray_Release(command->items);
        }
        HeapFree(GetProcessHeap(), 0, command);
        InterlockedDecrement(&g_objects);
        quit_when_idle();
    }
    return (ULONG)refs;
}

static HRESULT STDMETHODCALLTYPE command_key_state(IExecuteCommand *self, DWORD state)
{
    (void)self;
    (void)state;
    return S_OK;
}

static HRESULT STDMETHODCALLTYPE command_parameters(IExecuteCommand *self, LPCWSTR parameters)
{
    (void)self;
    (void)parameters;
    return S_OK;
}

static HRESULT STDMETHODCALLTYPE command_position(IExecuteCommand *self, POINT point)
{
    (void)self;
    (void)point;
    return S_OK;
}

static HRESULT STDMETHODCALLTYPE command_show(IExecuteCommand *self, int show)
{
    ((Command *)self)->show = show;
    return S_OK;
}

static HRESULT STDMETHODCALLTYPE command_no_ui(IExecuteCommand *self, BOOL no_ui)
{
    (void)self;
    (void)no_ui;
    return S_OK;
}

static HRESULT STDMETHODCALLTYPE command_directory(IExecuteCommand *self, LPCWSTR directory)
{
    (void)self;
    (void)directory;
    return S_OK;
}

/* Dateien der Auswahl als Argumente (jeweils in Anführungszeichen) an die App – wie »PDF-Tool.exe "%1"«. */
static HRESULT STDMETHODCALLTYPE command_execute(IExecuteCommand *self)
{
    Command *command = (Command *)self;
    static wchar_t arguments[MAX_ARGUMENTS];
    size_t used = 0;
    arguments[0] = L'\0';
    DWORD count = 0;
    if (command->items != NULL && SUCCEEDED(IShellItemArray_GetCount(command->items, &count))) {
        for (DWORD index = 0; index < count; index++) {
            IShellItem *item = NULL;
            if (FAILED(IShellItemArray_GetItemAt(command->items, index, &item))) {
                continue;
            }
            PWSTR path = NULL;
            if (SUCCEEDED(IShellItem_GetDisplayName(item, SIGDN_FILESYSPATH, &path)) && path != NULL) {
                size_t length = wcslen(path);
                if (used + length + 4 < MAX_ARGUMENTS) {
                    used += (size_t)swprintf(arguments + used, MAX_ARGUMENTS - used, L"%ls\"%ls\"", used ? L" " : L"", path);
                }
                CoTaskMemFree(path);
            }
            IShellItem_Release(item);
        }
    }
    int code = run_app(arguments, command->show, L"COM");
    g_done = TRUE;
    return code == 0 ? S_OK : E_FAIL;
}

static HRESULT STDMETHODCALLTYPE selection_query(IObjectWithSelection *self, REFIID riid, void **out)
{
    return command_query(&COMMAND_FROM_SELECTION(self)->execute, riid, out);
}

static ULONG STDMETHODCALLTYPE selection_add_ref(IObjectWithSelection *self)
{
    return command_add_ref(&COMMAND_FROM_SELECTION(self)->execute);
}

static ULONG STDMETHODCALLTYPE selection_release(IObjectWithSelection *self)
{
    return command_release(&COMMAND_FROM_SELECTION(self)->execute);
}

static HRESULT STDMETHODCALLTYPE selection_set(IObjectWithSelection *self, IShellItemArray *items)
{
    Command *command = COMMAND_FROM_SELECTION(self);
    if (items != NULL) {
        IShellItemArray_AddRef(items);
    }
    if (command->items != NULL) {
        IShellItemArray_Release(command->items);
    }
    command->items = items;
    return S_OK;
}

static HRESULT STDMETHODCALLTYPE selection_get(IObjectWithSelection *self, REFIID riid, void **out)
{
    Command *command = COMMAND_FROM_SELECTION(self);
    if (out == NULL) {
        return E_POINTER;
    }
    *out = NULL;
    if (command->items == NULL) {
        return E_FAIL;
    }
    return IShellItemArray_QueryInterface(command->items, riid, out);
}

static IExecuteCommandVtbl g_command_vtbl = {
    command_query, command_add_ref, command_release,
    command_key_state, command_parameters, command_position, command_show, command_no_ui, command_directory,
    command_execute,
};

static IObjectWithSelectionVtbl g_selection_vtbl = {
    selection_query, selection_add_ref, selection_release, selection_set, selection_get,
};

static HRESULT STDMETHODCALLTYPE factory_query(IClassFactory *self, REFIID riid, void **out)
{
    if (out == NULL) {
        return E_POINTER;
    }
    if (IsEqualIID(riid, &IID_IUnknown) || IsEqualIID(riid, &IID_IClassFactory)) {
        *out = self;
        return S_OK;
    }
    *out = NULL;
    return E_NOINTERFACE;
}

static ULONG STDMETHODCALLTYPE factory_add_ref(IClassFactory *self)
{
    (void)self;
    return 2;
}

static ULONG STDMETHODCALLTYPE factory_release(IClassFactory *self)
{
    (void)self;
    return 1;
}

static HRESULT STDMETHODCALLTYPE factory_create(IClassFactory *self, IUnknown *outer, REFIID riid, void **out)
{
    (void)self;
    if (out == NULL) {
        return E_POINTER;
    }
    *out = NULL;
    if (outer != NULL) {
        return CLASS_E_NOAGGREGATION;
    }
    Command *command = HeapAlloc(GetProcessHeap(), HEAP_ZERO_MEMORY, sizeof(Command));
    if (command == NULL) {
        return E_OUTOFMEMORY;
    }
    command->execute.lpVtbl = &g_command_vtbl;
    command->selection.lpVtbl = &g_selection_vtbl;
    command->refs = 1;
    command->show = SW_SHOWNORMAL;
    InterlockedIncrement(&g_objects);
    HRESULT result = command_query(&command->execute, riid, out);
    command_release(&command->execute);
    return result;
}

static HRESULT STDMETHODCALLTYPE factory_lock(IClassFactory *self, BOOL lock)
{
    (void)self;
    (void)lock;
    return S_OK;
}

static IClassFactoryVtbl g_factory_vtbl = { factory_query, factory_add_ref, factory_release, factory_create, factory_lock };
static IClassFactory g_factory = { &g_factory_vtbl };

/* Von Windows als COM-Server gestartet: Klasse anmelden, Aufruf abwarten, danach (oder nach SERVER_IDLE_MS) enden. */
static int run_server(void)
{
    if (FAILED(CoInitializeEx(NULL, COINIT_APARTMENTTHREADED))) {
        return 1;
    }
    DWORD cookie = 0;
    HRESULT result = CoRegisterClassObject(&CLSID_PDFTOOL_OPEN, (IUnknown *)&g_factory, CLSCTX_LOCAL_SERVER, REGCLS_SINGLEUSE, &cookie);
    if (SUCCEEDED(result)) {
        UINT_PTR timer = SetTimer(NULL, 0, SERVER_IDLE_MS, NULL);
        MSG message;
        while (GetMessageW(&message, NULL, 0, 0) > 0) {
            if (message.message == WM_TIMER && message.hwnd == NULL && message.wParam == timer && !(g_objects > 0 && !g_done)) {
                break;
            }
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
        KillTimer(NULL, timer);
        CoRevokeClassObject(cookie);
    }
    CoUninitialize();
    return SUCCEEDED(result) ? 0 : 1;
}

static BOOL is_embedding(const wchar_t *arguments)
{
    return wcsstr(arguments, L"-Embedding") != NULL || wcsstr(arguments, L"/Embedding") != NULL;
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR arguments, int show)
{
    (void)instance;
    (void)previous;
    if (is_embedding(arguments)) {
        return run_server();
    }
    return run_app(arguments, show, L"direkt");
}
