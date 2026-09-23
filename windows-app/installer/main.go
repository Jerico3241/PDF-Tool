package main

import (
	"archive/zip"
	"bytes"
	_ "embed"
	"fmt"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"syscall"
	"time"
	"unsafe"

	"golang.org/x/sys/windows"
	"golang.org/x/sys/windows/registry"
)

//go:embed payload.zip
var payload []byte

const (
	version     = "2.0.5"
	appFolder   = "Uebersichten-Ersteller"
	displayName = "Übersichten-Ersteller"
	exeName     = "Uebersichten-Ersteller.exe"
)

func main() {
	_ = setDPIAware()

	if hasFlag("/uninstall") {
		uninstall()
		return
	}

	inst, err := installDir()
	if err != nil {
		fatal("Installationsordner", err.Error())
		return
	}

	if hasFlag("/launch") {
		if !alreadyInstalled(inst) {
			if !ask(displayName, "Die App ist noch nicht eingerichtet.\n\nJetzt einrichten und starten?") {
				return
			}
			if err := setup(inst); err != nil {
				fatal("Einrichtung", err.Error())
				return
			}
		}
		if err := launch(inst); err != nil {
			fatal("Start fehlgeschlagen", err.Error())
		}
		return
	}

	text := displayName + " 2.0.5 wird auf diesem PC eingerichtet.\n\n" +
		"Ort: " + inst + "\n\n" +
		"Keine Administratorrechte nötig.\n\n" +
		"Einrichten und starten?"
	if !ask(displayName+" 2.0.5 einrichten", text) {
		return
	}
	if err := setup(inst); err != nil {
		fatal("Einrichtung", err.Error())
		return
	}
	info(displayName, "Version 2.0.5 ist eingerichtet.\n\nVerknüpfung: Desktop und Startmenü.\nDie App wird jetzt geöffnet.")
	if err := launch(inst); err != nil {
		fatal("Start fehlgeschlagen", err.Error())
	}
}

func setup(inst string) error {
	_ = removeLegacyInstalls()
	_ = removeLegacyShortcuts()
	if err := os.MkdirAll(inst, 0755); err != nil {
		return err
	}
	if err := unzip(payload, inst); err != nil {
		return fmt.Errorf("Dateien konnten nicht entpackt werden: %w", err)
	}
	if err := copySelf(inst); err != nil {
		return err
	}
	if err := os.WriteFile(filepath.Join(inst, "version.txt"), []byte(version+"\n"), 0644); err != nil {
		return err
	}
	if err := writeUninstall(inst); err != nil {
		return err
	}
	_ = registerApp(inst)
	_ = removeLegacyShortcuts()
	if err := createShortcuts(inst); err != nil {
		return fmt.Errorf("Verknüpfungen: %w", err)
	}
	return nil
}

func alreadyInstalled(inst string) bool {
	b, err := os.ReadFile(filepath.Join(inst, "version.txt"))
	if err != nil {
		return false
	}
	return strings.TrimSpace(string(b)) == version &&
		fileExists(filepath.Join(inst, "runtime", "pythonw.exe")) &&
		fileExists(filepath.Join(inst, "runtime", "DLLs", "_tkinter.pyd")) &&
		fileExists(filepath.Join(inst, "app", "start.py"))
}

func launch(inst string) error {
	py := filepath.Join(inst, "runtime", "pythonw.exe")
	script := filepath.Join(inst, "app", "start.py")
	if !fileExists(py) || !fileExists(script) {
		return fmt.Errorf("Installationsdateien fehlen.\nBitte das neue Setup erneut ausführen.")
	}
	logPath := filepath.Join(inst, "start.log")
	logFile, err := os.Create(logPath)
	if err != nil {
		logFile = nil
	}

	cmd := exec.Command(py, script)
	cmd.Dir = filepath.Join(inst, "app")
	dlls := filepath.Join(inst, "runtime", "DLLs")
	env := os.Environ()
	env = append(env,
		"TCL_LIBRARY="+filepath.Join(inst, "runtime", "tcl", "tcl8.6"),
		"TK_LIBRARY="+filepath.Join(inst, "runtime", "tcl", "tk8.6"),
		"PATH="+filepath.Join(inst, "runtime")+";"+dlls+";"+os.Getenv("PATH"),
		"PYTHONIOENCODING=utf-8",
	)
	cmd.Env = env
	if logFile != nil {
		cmd.Stdout = logFile
		cmd.Stderr = logFile
	}

	if err := cmd.Start(); err != nil {
		if logFile != nil {
			logFile.Close()
		}
		return err
	}

	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case waitErr := <-done:
		if logFile != nil {
			logFile.Close()
		}
		msg := readText(filepath.Join(inst, "fehler.log"))
		if strings.TrimSpace(msg) == "" {
			msg = readText(logPath)
		}
		if strings.TrimSpace(msg) == "" {
			msg = "Die App wurde sofort wieder beendet."
		}
		if waitErr != nil {
			return fmt.Errorf("%v\n\n%s", waitErr, msg)
		}
		return fmt.Errorf("%s", msg)
	case <-time.After(400 * time.Millisecond):
		return nil
	}
}

func copySelf(inst string) error {
	self, err := os.Executable()
	if err != nil {
		return err
	}
	dst := filepath.Join(inst, exeName)
	absSelf, _ := filepath.Abs(self)
	absDst, _ := filepath.Abs(dst)
	if strings.EqualFold(absSelf, absDst) {
		return nil
	}
	in, err := os.Open(self)
	if err != nil {
		return err
	}
	defer in.Close()
	out, err := os.Create(dst)
	if err != nil {
		return err
	}
	defer out.Close()
	_, err = io.Copy(out, in)
	return err
}

func registerApp(inst string) error {
	key, _, err := registry.CreateKey(
		registry.CURRENT_USER,
		`Software\Microsoft\Windows\CurrentVersion\Uninstall\Uebersichten-Ersteller`,
		registry.SET_VALUE,
	)
	if err != nil {
		return err
	}
	defer key.Close()
	exe := filepath.Join(inst, exeName)
	ico := filepath.Join(inst, "assets", "icon.ico")
	_ = key.SetStringValue("DisplayName", displayName)
	_ = key.SetStringValue("DisplayVersion", version)
	_ = key.SetStringValue("Publisher", "Jerico")
	_ = key.SetStringValue("InstallLocation", inst)
	_ = key.SetStringValue("UninstallString", `"`+exe+`" /uninstall`)
	if fileExists(ico) {
		_ = key.SetStringValue("DisplayIcon", ico)
	}
	_ = key.SetDWordValue("NoModify", 1)
	_ = key.SetDWordValue("NoRepair", 1)
	_ = key.SetDWordValue("EstimatedSize", 46000)
	return nil
}

func unregisterApp() {
	_ = registry.DeleteKey(
		registry.CURRENT_USER,
		`Software\Microsoft\Windows\CurrentVersion\Uninstall\Uebersichten-Ersteller`,
	)
}

func writeUninstall(inst string) error {
	body := "@echo off\r\n" +
		"echo " + displayName + " wird entfernt...\r\n" +
		"powershell -NoProfile -ExecutionPolicy Bypass -Command \"Start-Process -FilePath '%~dp0" + exeName + "' -ArgumentList '/uninstall' -Wait\"\r\n"
	return os.WriteFile(filepath.Join(inst, "Deinstallieren.bat"), []byte(body), 0644)
}

func uninstall() {
	inst, err := installDir()
	if err != nil {
		fatal("Deinstallation", err.Error())
		return
	}
	if !ask("Deinstallieren", displayName+" wirklich von diesem PC entfernen?") {
		return
	}
	_ = removeShortcuts()
	_ = removeLegacyShortcuts()
	if err := os.RemoveAll(inst); err != nil {
		fatal("Deinstallation", err.Error())
		return
	}
	unregisterApp()
	info(displayName, "Die App wurde entfernt.")
}

func createShortcuts(inst string) error {
	py := filepath.Join(inst, "runtime", "pythonw.exe")
	script := filepath.Join(inst, "app", "start.py")
	appDir := filepath.Join(inst, "app")
	ico := filepath.Join(inst, "assets", "icon.ico")
	// Direkt pythonw starten, nicht die 44-MB-Setup-Datei. Sonst lädt jeder
	// Start das eingebettete Paket und die App wirkt träge.
	ps := fmt.Sprintf(`
$ErrorActionPreference = 'Stop'
$sh = New-Object -ComObject WScript.Shell
function New-Link($path) {
  $l = $sh.CreateShortcut($path)
  $l.TargetPath = %q
  $l.Arguments = '-s -OO ' + [char]34 + %q + [char]34
  $l.WorkingDirectory = %q
  $l.WindowStyle = 1
  $l.Description = %q
  if (Test-Path -LiteralPath %q) { $l.IconLocation = %q }
  $l.Save()
}
$desktop = [Environment]::GetFolderPath('Desktop')
New-Link (Join-Path $desktop %q)
$programs = Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs\%s'
New-Item -ItemType Directory -Force -Path $programs | Out-Null
New-Link (Join-Path $programs %q)
`, py, script, appDir, displayName, ico, ico, displayName+".lnk", displayName, displayName+".lnk")
	return runHidden("powershell", "-NoProfile", "-STA", "-ExecutionPolicy", "Bypass", "-Command", ps)
}

func removeShortcuts() error {
	script := fmt.Sprintf(`
$desktop = Join-Path ([Environment]::GetFolderPath('Desktop')) %q
if (Test-Path -LiteralPath $desktop) { Remove-Item -LiteralPath $desktop -Force }
$programs = Join-Path ([Environment]::GetFolderPath('StartMenu')) 'Programs\%s'
if (Test-Path -LiteralPath $programs) { Remove-Item -LiteralPath $programs -Recurse -Force }
`, displayName+".lnk", displayName)
	return runHidden("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script)
}

func removeLegacyShortcuts() error {
	script := `
$names = @('VertraView.lnk', 'Vertragsübersicht.lnk', 'VertragDesk.lnk', 'Übersichten-Ersteller.lnk', 'Uebersichten-Ersteller.lnk')
$desktop = [Environment]::GetFolderPath('Desktop')
foreach ($n in $names) {
  $p = Join-Path $desktop $n
  if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force }
}
$start = [Environment]::GetFolderPath('StartMenu')
foreach ($folder in @('VertraView', 'Vertragsübersicht', 'VertragDesk', 'Übersichten-Ersteller', 'UebersichtenErsteller')) {
  $p = Join-Path $start "Programs\$folder"
  if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Recurse -Force }
}
`
	return runHidden("powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script)
}

func runHidden(name string, args ...string) error {
	cmd := exec.Command(name, args...)
	cmd.SysProcAttr = &syscall.SysProcAttr{HideWindow: true}
	out, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("%s: %s", err, strings.TrimSpace(string(out)))
	}
	return nil
}

func unzip(blob []byte, dest string) error {
	r, err := zip.NewReader(bytes.NewReader(blob), int64(len(blob)))
	if err != nil {
		return err
	}
	for _, f := range r.File {
		name := filepath.Clean(f.Name)
		if strings.HasPrefix(name, "..") {
			continue
		}
		path := filepath.Join(dest, name)
		if !strings.HasPrefix(strings.ToLower(path), strings.ToLower(dest)) {
			continue
		}
		if f.FileInfo().IsDir() {
			if err := os.MkdirAll(path, 0755); err != nil {
				return err
			}
			continue
		}
		if err := os.MkdirAll(filepath.Dir(path), 0755); err != nil {
			return err
		}
		rc, err := f.Open()
		if err != nil {
			return err
		}
		out, err := os.OpenFile(path, os.O_CREATE|os.O_WRONLY|os.O_TRUNC, 0755)
		if err != nil {
			rc.Close()
			return err
		}
		_, copyErr := io.Copy(out, rc)
		out.Close()
		rc.Close()
		if copyErr != nil {
			return copyErr
		}
	}
	return nil
}

func installDir() (string, error) {
	base := os.Getenv("LOCALAPPDATA")
	if base == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return "", err
		}
		base = filepath.Join(home, "AppData", "Local")
	}
	return filepath.Join(base, appFolder), nil
}

func hasFlag(flag string) bool {
	for _, a := range os.Args[1:] {
		if strings.EqualFold(a, flag) {
			return true
		}
	}
	return false
}

func removeLegacyInstalls() error {
	base := os.Getenv("LOCALAPPDATA")
	if base == "" {
		home, err := os.UserHomeDir()
		if err != nil {
			return err
		}
		base = filepath.Join(home, "AppData", "Local")
	}
	for _, name := range []string{"VertraView", "Vertragsübersicht", "VertragDesk"} {
		p := filepath.Join(base, name)
		_ = os.RemoveAll(p)
	}
	return nil
}

func dirExists(p string) bool {
	st, err := os.Stat(p)
	return err == nil && st.IsDir()
}

func fileExists(p string) bool {
	st, err := os.Stat(p)
	return err == nil && !st.IsDir()
}

func readText(p string) string {
	b, err := os.ReadFile(p)
	if err != nil {
		return ""
	}
	return string(b)
}

var (
	user32          = windows.NewLazySystemDLL("user32.dll")
	procMessageBoxW = user32.NewProc("MessageBoxW")
	shcore          = windows.NewLazySystemDLL("Shcore.dll")
)

func setDPIAware() error {
	proc := shcore.NewProc("SetProcessDpiAwareness")
	r, _, err := proc.Call(2)
	if r == 0 && err != nil && err != syscall.Errno(0) {
		return err
	}
	return nil
}

func messageBox(title, text string, flags uint) int {
	r, _, _ := procMessageBoxW.Call(
		0,
		uintptr(unsafe.Pointer(windows.StringToUTF16Ptr(text))),
		uintptr(unsafe.Pointer(windows.StringToUTF16Ptr(title))),
		uintptr(flags),
	)
	return int(r)
}

func ask(title, text string) bool {
	return messageBox(title, text, 0x24) == 6
}

func info(title, text string) {
	messageBox(title, text, 0x40)
}

func fatal(title, text string) {
	messageBox(title, text, 0x10)
}
