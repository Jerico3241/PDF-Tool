/*
 * PDF Tool – Startprogramm (PDF-Tool.exe im Programmordner).
 *
 * Startet die eingebettete Python-Laufzeit mit der App:
 *     <Programmordner>\runtime\pythonw.exe -s -OO "<Programmordner>\app\start.py" <Argumente>
 * Die Argumente (z. B. die PDF bei »Öffnen mit«) werden unverändert weitergegeben.
 *
 * Warum ein eigenes Programm: Windows zeigt in »Öffnen mit«, bei den Standard-Apps und in der
 * Taskleiste das Symbol und den Namen der gestarteten EXE. Mit pythonw.exe erschiene dort Python.
 * Diese EXE trägt Symbol und Versionsangaben von PDF Tool und endet, sobald die App gestartet ist.
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
    if (!CreateProcessW(python, line, NULL, NULL, FALSE, 0, NULL, workdir, &startup, &process)) {
        wchar_t text[256];
        swprintf(text, 256, L"PDF Tool konnte nicht gestartet werden (Fehler %lu).", GetLastError());
        fail(text);
        return 1;
    }
    /* Das Fenster der App darf in den Vordergrund (dieses Programm wurde vom Benutzer gestartet). */
    AllowSetForegroundWindow(process.dwProcessId);
    CloseHandle(process.hThread);
    CloseHandle(process.hProcess);
    return 0;
}
