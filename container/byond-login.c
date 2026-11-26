#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <fcntl.h>
#include <io.h>
#include <stdio.h>
#include <wchar.h>

struct dialog {
    HWND window, account, password, save, automatic, login;
};

static BOOL is_class(HWND window, const wchar_t *expected)
{
    wchar_t name[32];
    return GetClassNameW(window, name, 32) && wcscmp(name, expected) == 0;
}

static BOOL assign(HWND *control, HWND candidate)
{
    if (*control)
        return FALSE;
    *control = candidate;
    return TRUE;
}

static BOOL find_dialog(HWND window, DWORD pager, struct dialog *match)
{
    DWORD pid = 0;
    wchar_t text[96];
    GetWindowThreadProcessId(window, &pid);
    if (pid != pager || !IsWindowVisible(window) || !IsWindowEnabled(window) ||
        !is_class(window, L"#32770") ||
        !GetWindowTextW(window, text, 96) || wcscmp(text, L"Login") != 0)
        return FALSE;

    struct dialog dialog = { .window = window };
    for (HWND child = GetWindow(window, GW_CHILD); child; child = GetWindow(child, GW_HWNDNEXT)) {
        LONG_PTR style = GetWindowLongPtrW(child, GWL_STYLE);
        if (is_class(child, L"ComboBox")) {
            HWND edit = FindWindowExW(child, NULL, L"Edit", NULL);
            if (edit && !(GetWindowLongPtrW(edit, GWL_STYLE) & (ES_PASSWORD | ES_READONLY))) {
                if (!assign(&dialog.account, edit))
                    return FALSE;
            }
        } else if (is_class(child, L"Edit") && (style & ES_PASSWORD) && !(style & ES_READONLY)) {
            if (!assign(&dialog.password, child))
                return FALSE;
        } else if (is_class(child, L"Button")) {
            /* GetWindowText cannot retrieve another process's child control text. */
            DWORD_PTR length;
            if (!SendMessageTimeoutW(child, WM_GETTEXT, 96, (LPARAM)text,
                                     SMTO_ABORTIFHUNG | SMTO_BLOCK, 500, &length))
                return FALSE;
            if ((style & BS_TYPEMASK) == BS_AUTOCHECKBOX) {
                if (wcscmp(text, L"Save password") == 0 && !assign(&dialog.save, child))
                    return FALSE;
                if (wcscmp(text, L"Automatically login when program starts") == 0 &&
                    !assign(&dialog.automatic, child))
                    return FALSE;
            }
            if (wcscmp(text, L"Login") == 0 && !assign(&dialog.login, child))
                return FALSE;
        }
    }
    if (!dialog.account || !dialog.password || !dialog.save || !dialog.automatic || !dialog.login ||
        !IsWindowEnabled(dialog.account))
        return FALSE;
    *match = dialog;
    return TRUE;
}

struct search {
    DWORD pid;
    unsigned matches;
    struct dialog dialog;
};

static BOOL CALLBACK find_login(HWND window, LPARAM arg)
{
    struct search *search = (struct search *)arg;
    if (find_dialog(window, search->pid, &search->dialog))
        ++search->matches;
    return search->matches < 2;
}

static BOOL send(HWND window, UINT message, WPARAM wparam, LPARAM lparam, DWORD_PTR *result)
{
    return SendMessageTimeoutW(window, message, wparam, lparam,
                               SMTO_ABORTIFHUNG | SMTO_BLOCK, 1000, result) != 0;
}

static BOOL submit(struct dialog *dialog, const wchar_t *account, const wchar_t *password)
{
    DWORD_PTR result;
    HWND combo = GetParent(dialog->account);
    if (!send(dialog->account, WM_SETTEXT, 0, (LPARAM)account, &result) || !result ||
        !send(dialog->window, WM_COMMAND, MAKEWPARAM(GetDlgCtrlID(combo), CBN_EDITCHANGE),
              (LPARAM)combo, &result) ||
        !IsWindowEnabled(dialog->password) || !IsWindowEnabled(dialog->save) ||
        !IsWindowEnabled(dialog->automatic) ||
        !send(dialog->save, BM_SETCHECK, BST_CHECKED, 0, &result) ||
        !send(dialog->automatic, BM_SETCHECK, BST_CHECKED, 0, &result) ||
        !send(dialog->save, BM_GETCHECK, 0, 0, &result) || result != BST_CHECKED ||
        !send(dialog->automatic, BM_GETCHECK, 0, 0, &result) || result != BST_CHECKED)
        return FALSE;

    BOOL ready = send(dialog->password, WM_SETTEXT, 0, (LPARAM)password, &result) && result &&
                 IsWindowEnabled(dialog->login);
    /* Post the button notification once; the pager can block while logging in. */
    if (ready && PostMessageW(dialog->window, WM_COMMAND,
                              MAKEWPARAM(GetDlgCtrlID(dialog->login), BN_CLICKED),
                              (LPARAM)dialog->login))
        return TRUE;
    send(dialog->password, WM_SETTEXT, 0, (LPARAM)L"", &result);
    return FALSE;
}

static BOOL read_password(wchar_t *password, int capacity)
{
    char bytes[1027];
    if (_setmode(_fileno(stdin), _O_BINARY) == -1)
        return FALSE;
    size_t size = fread(bytes, 1, sizeof(bytes), stdin);
    BOOL valid = !ferror(stdin) && size < sizeof(bytes);
    fclose(stdin);
    if (size && bytes[size - 1] == '\n') {
        --size;
        if (size && bytes[size - 1] == '\r')
            --size;
    }
    if (!size || size > 1024)
        valid = FALSE;
    for (size_t i = 0; valid && i < size; ++i)
        if ((unsigned char)bytes[i] < 32 || bytes[i] == 127)
            valid = FALSE;
    int count = valid ? MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, bytes, (int)size,
                                           password, capacity - 1) : 0;
    SecureZeroMemory(bytes, sizeof(bytes));
    if (!count)
        return FALSE;
    password[count] = 0;
    return TRUE;
}

int wmain(int argc, wchar_t **argv)
{
    static const wchar_t pager[] = L"C:\\Program Files (x86)\\BYOND\\bin\\byond.exe";
    wchar_t command[350], password[1025] = {0};
    PROCESS_INFORMATION process;
    STARTUPINFOW startup = { .cb = sizeof(startup) };

    if (argc < 2 || argc > 3 ||
        swprintf(command, 350, L"\"%ls\"%ls%ls", pager, argc == 3 ? L" " : L"",
                 argc == 3 ? argv[2] : L"") < 0)
        return 1;
    setvbuf(stdin, NULL, _IONBF, 0);
    BOOL have_password = read_password(password, 1025);
    if (!CreateProcessW(pager, command, NULL, NULL, FALSE, 0, NULL, NULL, &startup, &process)) {
        SecureZeroMemory(password, sizeof(password));
        fputs("Could not start the BYOND pager\n", stderr);
        return 1;
    }
    CloseHandle(process.hThread);
    if (have_password) {
        ULONGLONG deadline = GetTickCount64() + 30000;
        BOOL submitted = FALSE;
        while (GetTickCount64() < deadline &&
               WaitForSingleObject(process.hProcess, 200) == WAIT_TIMEOUT) {
            struct search search = { .pid = process.dwProcessId };
            EnumWindows(find_login, (LPARAM)&search);
            if (search.matches == 1) {
                submitted = submit(&search.dialog, argv[1], password);
                break;
            }
        }
        if (!submitted)
            fputs("BYOND login automation did not submit; if not already signed in, use the pager to log in manually\n", stderr);
    } else {
        fputs("Invalid BYOND password file; use the pager to log in manually\n", stderr);
    }
    SecureZeroMemory(password, sizeof(password));
    DWORD exit_code = 1;
    if (WaitForSingleObject(process.hProcess, INFINITE) == WAIT_OBJECT_0)
        GetExitCodeProcess(process.hProcess, &exit_code);
    CloseHandle(process.hProcess);
    return (int)exit_code;
}
