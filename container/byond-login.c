#define WIN32_LEAN_AND_MEAN
#define COBJMACROS
#include <windows.h>
#include <oleacc.h>
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

struct link_search {
    const wchar_t *name;
    unsigned remaining;
    unsigned nodes;
    unsigned accessible_windows;
    HRESULT last_error;
    BOOL found;
    HRESULT result;
};

static HRESULT activate_if_match(IAccessible *accessible, VARIANT child,
                                 struct link_search *search)
{
    BSTR name = NULL;
    VARIANT role;
    VariantInit(&role);
    HRESULT result = IAccessible_get_accName(accessible, child, &name);
    if (SUCCEEDED(result) && name && wcscmp(name, search->name) == 0) {
        result = IAccessible_get_accRole(accessible, child, &role);
        if (SUCCEEDED(result) && role.vt == VT_I4 &&
            (role.lVal == ROLE_SYSTEM_LINK || role.lVal == ROLE_SYSTEM_PUSHBUTTON ||
             role.lVal == ROLE_SYSTEM_STATICTEXT)) {
            search->found = TRUE;
            search->result = IAccessible_accDoDefaultAction(accessible, child);
            result = search->result;
        }
    }
    SysFreeString(name);
    VariantClear(&role);
    return result;
}

static HRESULT activate_link(IAccessible *accessible, struct link_search *search, unsigned depth)
{
    if (depth > 16 || !search->remaining)
        return S_FALSE;
    VARIANT self;
    VariantInit(&self);
    self.vt = VT_I4;
    self.lVal = CHILDID_SELF;
    HRESULT result = activate_if_match(accessible, self, search);
    if (search->found)
        return result;

    LONG count = 0;
    result = IAccessible_get_accChildCount(accessible, &count);
    if (FAILED(result))
        return result;
    if (count > 2048)
        return E_FAIL;

    for (LONG index = 1; index <= count && search->remaining; ++index, --search->remaining) {
        ++search->nodes;
        VARIANT child;
        VariantInit(&child);
        child.vt = VT_I4;
        child.lVal = index;
        result = activate_if_match(accessible, child, search);
        if (search->found)
            return result;

        IDispatch *dispatch = NULL;
        result = IAccessible_get_accChild(accessible, child, &dispatch);
        VariantClear(&child);
        if (SUCCEEDED(result) && dispatch) {
            IAccessible *nested = NULL;
            result = IDispatch_QueryInterface(dispatch, &IID_IAccessible, (void **)&nested);
            IDispatch_Release(dispatch);
            if (SUCCEEDED(result) && nested) {
                result = activate_link(nested, search, depth + 1);
                IAccessible_Release(nested);
                if (search->found)
                    return result;
            }
        }
    }
    return S_FALSE;
}

static BOOL inspect_link_window(HWND window, struct link_search *search)
{
    ++search->nodes;
    wchar_t class_name[32], text[96];
    if (GetClassNameW(window, class_name, 32) && wcscmp(class_name, L"Button") == 0 &&
        SendMessageTimeoutW(window, WM_GETTEXT, 96, (LPARAM)text,
                            SMTO_ABORTIFHUNG | SMTO_BLOCK, 500, NULL) &&
        wcscmp(text, search->name) == 0 && IsWindowEnabled(window)) {
        if (SendMessageTimeoutW(window, BM_CLICK, 0, 0, SMTO_ABORTIFHUNG | SMTO_BLOCK, 500, NULL)) {
            search->found = TRUE;
            search->result = S_OK;
            return FALSE;
        }
    }

    IAccessible *accessible = NULL;
    HRESULT result = AccessibleObjectFromWindow(window, OBJID_CLIENT, &IID_IAccessible,
                                                (void **)&accessible);
    search->last_error = result;
    if (SUCCEEDED(result) && accessible) {
        ++search->accessible_windows;
        wchar_t debug[2];
        if (GetEnvironmentVariableW(L"BYOND_LOGIN_DEBUG", debug, 2)) {
            VARIANT self;
            VARIANT role;
            BSTR name = NULL;
            LONG children = -1;
            VariantInit(&self);
            VariantInit(&role);
            self.vt = VT_I4;
            self.lVal = CHILDID_SELF;
            HRESULT name_result = IAccessible_get_accName(accessible, self, &name);
            HRESULT role_result = IAccessible_get_accRole(accessible, self, &role);
            IAccessible_get_accChildCount(accessible, &children);
            fprintf(stderr, "BYOND accessibility window: self-name=%u name-hr=0x%08lx "
                            "role=%ld role-hr=0x%08lx children=%ld\n",
                    name ? (unsigned)SysStringLen(name) : 0,
                    (unsigned long)name_result,
                    role.vt == VT_I4 ? role.lVal : -1,
                    (unsigned long)role_result, children);
            SysFreeString(name);
            VariantClear(&role);
        }
        activate_link(accessible, search, 0);
        IAccessible_Release(accessible);
    }
    return !search->found && search->remaining;
}

struct window_search {
    DWORD pager;
    struct link_search *link;
};

static BOOL CALLBACK inspect_child_window(HWND window, LPARAM arg)
{
    struct window_search *search = (struct window_search *)arg;
    /* WebView2 renders the pager content in a separate process. */
    return inspect_link_window(window, search->link);
}

static BOOL CALLBACK inspect_top_window(HWND window, LPARAM arg)
{
    struct window_search *search = (struct window_search *)arg;
    DWORD pid = 0;
    GetWindowThreadProcessId(window, &pid);
    if (pid != search->pager)
        return TRUE;
    if (!inspect_link_window(window, search->link))
        return FALSE;
    EnumChildWindows(window, inspect_child_window, arg);
    return !search->link->found && search->link->remaining;
}

static BOOL pager_link(DWORD pager, const wchar_t *name, BOOL *found, unsigned *nodes)
{
    struct link_search link = { .name = name, .remaining = 10000 };
    struct window_search windows = { .pager = pager, .link = &link };
    EnumWindows(inspect_top_window, (LPARAM)&windows);
    *found = link.found;
    *nodes = link.nodes;
    if (!link.found && wcscmp(name, L"Logout") == 0) {
        fprintf(stderr,
                "BYOND accessibility scan: %u windows, %u accessible, last HRESULT 0x%08lx\n",
                link.nodes, link.accessible_windows, (unsigned long)link.last_error);
    }
    return link.found && SUCCEEDED(link.result);
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
    HRESULT com = CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
    if (FAILED(com)) {
        SecureZeroMemory(password, sizeof(password));
        fputs("Could not initialize pager accessibility\n", stderr);
        return 1;
    }
    if (!CreateProcessW(pager, command, NULL, NULL, FALSE, 0, NULL, NULL, &startup, &process)) {
        SecureZeroMemory(password, sizeof(password));
        CoUninitialize();
        fputs("Could not start the BYOND pager\n", stderr);
        return 1;
    }
    CloseHandle(process.hThread);
    if (have_password) {
        ULONGLONG deadline = GetTickCount64() + 120000;
        BOOL submitted = FALSE;
        BOOL clicked_logout = FALSE;
        BOOL attempted_logout = FALSE, attempted_login = FALSE;
        unsigned last_scan_nodes = 0;
        ULONGLONG next_link_scan = GetTickCount64() + 1000;
        while (GetTickCount64() < deadline &&
               WaitForSingleObject(process.hProcess, 200) == WAIT_TIMEOUT) {
            struct search search = { .pid = process.dwProcessId };
            EnumWindows(find_login, (LPARAM)&search);
            if (search.matches == 1) {
                submitted = submit(&search.dialog, argv[1], password);
                if (submitted)
                    fputs("BYOND login submitted once\n", stderr);
                break;
            }
            if (search.matches > 1)
                break;

            if (GetTickCount64() >= next_link_scan && !attempted_logout) {
                BOOL found = FALSE;
                BOOL activated = pager_link(process.dwProcessId, L"Logout", &found,
                                            &last_scan_nodes);
                attempted_logout = found;
                next_link_scan = GetTickCount64() + 1000;
                if (found) {
                    if (!activated) {
                        fputs("Could not activate the BYOND Logout link\n", stderr);
                        break;
                    }
                    clicked_logout = TRUE;
                    fputs("BYOND Guest session detected; signed out\n", stderr);
                    Sleep(500);
                    continue;
                }
            }
            if (clicked_logout && !attempted_login &&
                GetTickCount64() >= next_link_scan) {
                BOOL found = FALSE;
                BOOL activated = pager_link(process.dwProcessId, L"Login", &found,
                                            &last_scan_nodes);
                attempted_login = found;
                next_link_scan = GetTickCount64() + 1000;
                if (found) {
                    if (!activated) {
                        fputs("Could not activate the BYOND Login link\n", stderr);
                        break;
                    }
                    fputs("Opened the BYOND Login dialog\n", stderr);
                    Sleep(500);
                }
            }
        }
        if (!submitted && !clicked_logout)
            fprintf(stderr, "No accessible BYOND Logout link found (%u nodes inspected)\n",
                    last_scan_nodes);
        else if (!submitted && clicked_logout && !attempted_login)
            fprintf(stderr, "No accessible BYOND Login link found (%u nodes inspected)\n",
                    last_scan_nodes);
        else if (!submitted && clicked_logout && attempted_login)
            fputs("BYOND Login dialog did not appear after opening the Login link\n", stderr);
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
    CoUninitialize();
    return (int)exit_code;
}
