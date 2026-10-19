/*
 * PDF Tool – Startprogramm (PDF-Tool.exe im Programmordner).
 *
 * Startet die eingebettete Python-Laufzeit mit der App:
 *     <Programmordner>\runtime\pythonw.exe -s -OO "<Programmordner>\app\start.py" <Argumente>
 * Die Argumente (z. B. die PDF bei »Öffnen mit«) werden unverändert weitergegeben.
 *
 * Warum ein eigenes Programm: Windows zeigt in »Öffnen mit«, bei den Standard-Apps und in der
 * Taskleiste das Symbol und den Namen der gestarteten EXE. Mit pythonw.exe erschiene dort Python.
 * Diese EXE trägt Symbol und Versionsangaben von PDF Tool und endet, sobald die App die übergebenen Dateien
 * gesichert hat (siehe unten).
 * Die App verlässt dabei den Job des aufrufenden Programms (siehe unten).
 */
#define WIN32_LEAN_AND_MEAN
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#include <windows.h>
#include <stdio.h>
#include <wchar.h>

#define START_WAIT_MS 15000

static void fail(const wchar_t *text)
{
    MessageBoxW(NULL, text, L"PDF Tool", MB_OK | MB_ICONERROR);
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR arguments, int show)
{
    (void)instance;
    (void)previous;
    wchar_t folder[32768];
    DWORD length = GetModuleFileNameW(NULL, folder, (DWORD)(sizeof(folder) / sizeof(folder[0])));
    if (length == 0 || length >= sizeof(folder) / sizeof(folder[0])) {
        fail(L"PDF Tool konnte seinen Programmordner nicht bestimmen.");
        return 1;
    }
    wchar_t *slash = wcsrchr(folder, L'\\');
    if (slash == NULL) {
        fail(L"PDF Tool konnte seinen Programmordner nicht bestimmen.");
        return 1;
    }
    *slash = L'\0';

    size_t size = wcslen(folder) * 3 + wcslen(arguments) + 64;
    wchar_t *python = HeapAlloc(GetProcessHeap(), 0, size * sizeof(wchar_t));
    wchar_t *workdir = HeapAlloc(GetProcessHeap(), 0, size * sizeof(wchar_t));
    wchar_t *line = HeapAlloc(GetProcessHeap(), 0, size * sizeof(wchar_t));
    if (python == NULL || workdir == NULL || line == NULL) {
        fail(L"PDF Tool konnte nicht gestartet werden (zu wenig Arbeitsspeicher).");
        return 1;
    }
    swprintf(python, size, L"%ls\\runtime\\pythonw.exe", folder);
    swprintf(workdir, size, L"%ls\\app", folder);
    swprintf(line, size, L"\"%ls\" -s -OO \"%ls\\start.py\"%ls%ls", python, workdir, arguments[0] ? L" " : L"", arguments);
    if (GetFileAttributesW(python) == INVALID_FILE_ATTRIBUTES) {
        fail(L"PDF Tool ist unvollständig installiert (runtime\\pythonw.exe fehlt).\n\nBitte das Setup erneut ausführen.");
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
     * Startprogramm wartet deshalb, bis die App die Datei gesichert hat (start.py setzt dieses Ereignis), höchstens
     * START_WAIT_MS – oder bis die App endet (Übergabe an die schon laufende App).
     */
    wchar_t event_name[64];
    swprintf(event_name, 64, L"Local\\PDFTool-Start-%lu", GetCurrentProcessId());
    HANDLE ready = CreateEventW(NULL, TRUE, FALSE, event_name);
    if (ready != NULL) {
        SetEnvironmentVariableW(L"PDFTOOL_START_EVENT", event_name);
    }
    BOOL started = CreateProcessW(python, line, NULL, NULL, FALSE, CREATE_BREAKAWAY_FROM_JOB, NULL, workdir, &startup, &process);
    if (!started && GetLastError() == ERROR_ACCESS_DENIED) {
        started = CreateProcessW(python, line, NULL, NULL, FALSE, 0, NULL, workdir, &startup, &process);
    }
    if (!started) {
        if (ready != NULL) {
            CloseHandle(ready);
        }
        wchar_t text[256];
        swprintf(text, 256, L"PDF Tool konnte nicht gestartet werden (Fehler %lu).", GetLastError());
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
