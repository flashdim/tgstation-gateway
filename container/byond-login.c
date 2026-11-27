#define WIN32_LEAN_AND_MEAN
#define COBJMACROS
#include <windows.h>
#include <oleacc.h>
#include <fcntl.h>
#include <io.h>
#include <stdio.h>
#include <wchar.h>
#include <wctype.h>

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
    const wchar_t *account;
    BOOL report;
    unsigned reported;
    unsigned remaining;
    unsigned nodes;
    unsigned accessible_windows;
    HRESULT last_error;
    BOOL found;
    HRESULT result;
};

static BOOL same_label(const wchar_t *text, size_t length, const wchar_t *label)
{
    size_t size = wcslen(label);
    return length == size && _wcsnicmp(text, label, size) == 0;
}

/* Matches BYOND's account links, tolerating case, spacing, and wording. */
static BOOL link_matches(const wchar_t *text, const wchar_t *wanted)
{
    if (!text)
        return FALSE;
    while (iswspace(*text))
        ++text;
    size_t length = wcslen(text);
    while (length && iswspace(text[length - 1]))
        --length;
    if (wcscmp(wanted, L"Login") == 0)
        return same_label(text, length, L"Login") || same_label(text, length, L"Log in") ||
               same_label(text, length, L"Sign in");
    return same_label(text, length, L"Logout") || same_label(text, length, L"Log out") ||
           same_label(text, length, L"Sign out");
}

/* BYOND compares keys as ckeys: lowercase letters and digits only. */
static BOOL same_ckey(const wchar_t *text, const wchar_t *account)
{
    if (!text)
        return FALSE;
    for (;;) {
        while (*text && !iswalnum(*text))
            ++text;
        while (*account && !iswalnum(*account))
            ++account;
        if (!*text || !*account)
            return !*text && !*account;
        if (towlower(*text++) != towlower(*account++))
            return FALSE;
    }
}

static BOOL mentions_account(const wchar_t *text)
{
    for (; text && *text; ++text)
        if (!_wcsnicmp(text, L"log", 3) || !_wcsnicmp(text, L"sign", 4))
            return TRUE;
    return FALSE;
}

/* Lists candidate controls once, after the Login link could not be found. */
static void report_node(struct link_search *search, BSTR name, const VARIANT *role)
{
    LONG kind = role->vt == VT_I4 ? role->lVal : -1;
    if (!search->report || search->reported >= 80 ||
        (kind != ROLE_SYSTEM_LINK && kind != ROLE_SYSTEM_PUSHBUTTON &&
         kind != ROLE_SYSTEM_MENUITEM && !mentions_account(name)))
        return;
    char label[49] = "";
    unsigned used = 0;
    for (const wchar_t *c = name; c && *c && used < 48; ++c)
        label[used++] = *c >= 32 && *c < 127 ? (char)*c : '?';
    label[used] = 0;
    ++search->reported;
    fprintf(stderr, "BYOND accessible candidate: role=%ld name=\"%s\"\n", kind, label);
}

static HRESULT activate_if_match(IAccessible *accessible, VARIANT child,
                                 struct link_search *search)
{
    BSTR name = NULL;
    VARIANT role;
    VariantInit(&role);
    HRESULT result = IAccessible_get_accName(accessible, child, &name);
    if (SUCCEEDED(result) && search->account) {
        if (name && same_ckey(name, search->account)) {
            search->found = TRUE;
            search->result = S_OK;
        }
    } else if (SUCCEEDED(result) && search->report && name) {
        if (SUCCEEDED(IAccessible_get_accRole(accessible, child, &role)))
            report_node(search, name, &role);
        VariantClear(&role);
    } else if (SUCCEEDED(result) && link_matches(name, search->name)) {
        result = IAccessible_get_accRole(accessible, child, &role);
        if (SUCCEEDED(result) && role.vt == VT_I4 &&
            (role.lVal == ROLE_SYSTEM_LINK || role.lVal == ROLE_SYSTEM_PUSHBUTTON ||
             role.lVal == ROLE_SYSTEM_MENUITEM || role.lVal == ROLE_SYSTEM_STATICTEXT ||
             role.lVal == ROLE_SYSTEM_TEXT)) {
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
        !search->account && !search->report && link_matches(text, search->name) &&
        IsWindowEnabled(window)) {
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
    if (pid != search->pager || (search->link->account && is_class(window, L"#32770")))
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

/* The pager's Home page shows "<account> | Logout" once that account is signed in. */
static BOOL signed_in_as(DWORD pager, const wchar_t *account)
{
    const wchar_t *c = account;
    while (*c && !iswalnum(*c))
        ++c;
    if (!*c)
        return FALSE;
    struct link_search link = { .name = L"", .account = account, .remaining = 10000 };
    struct window_search windows = { .pager = pager, .link = &link };
    EnumWindows(inspect_top_window, (LPARAM)&windows);
    return link.found;
}

static void report_pager_links(DWORD pager)
{
    struct link_search link = { .name = L"", .report = TRUE, .remaining = 10000 };
    struct window_search windows = { .pager = pager, .link = &link };
    EnumWindows(inspect_top_window, (LPARAM)&windows);
    fprintf(stderr, "BYOND accessible candidates listed: %u\n", link.reported);
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
    wchar_t command[350], connect[350], password[1025] = {0};
    PROCESS_INFORMATION process;
    STARTUPINFOW startup = { .cb = sizeof(startup) };

    if (argc < 2 || argc > 3 || swprintf(command, 350, L"\"%ls\"", pager) < 0 ||
        (argc == 3 && (wcsncmp(argv[2], L"byond://", 8) != 0 ||
                       swprintf(connect, 350, L"\"%ls\" %ls", pager, argv[2]) < 0)))
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
        BOOL submitted = FALSE, verified = FALSE;
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

            if (GetTickCount64() >= next_link_scan && !attempted_logout &&
                signed_in_as(process.dwProcessId, argv[1])) {
                verified = TRUE;
                break;
            }
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
        SecureZeroMemory(password, sizeof(password));
        if (submitted) {
            ULONGLONG verify_deadline = GetTickCount64() + 60000;
            while (!verified && GetTickCount64() < verify_deadline &&
                   WaitForSingleObject(process.hProcess, 1000) == WAIT_TIMEOUT)
                verified = signed_in_as(process.dwProcessId, argv[1]);
        }
        if (verified) {
            fprintf(stderr, "BYOND signed in as %ls\n", argv[1]);
        } else if (submitted) {
            fprintf(stderr, "BYOND did not show %ls as signed in; check the password\n", argv[1]);
        } else if (!clicked_logout)
            fprintf(stderr, "No accessible BYOND Logout link found (%u nodes inspected)\n",
                    last_scan_nodes);
        else if (!submitted && clicked_logout && !attempted_login) {
            fprintf(stderr, "No accessible BYOND Login link found (%u nodes inspected)\n",
                    last_scan_nodes);
            if (WaitForSingleObject(process.hProcess, 0) == WAIT_TIMEOUT)
                report_pager_links(process.dwProcessId);
        }
        else if (!submitted && clicked_logout && attempted_login)
            fputs("BYOND Login dialog did not appear after opening the Login link\n", stderr);
        if (!submitted && !verified)
            fputs("BYOND login automation did not submit; if not already signed in, use the pager to log in manually\n", stderr);
        if (argc == 3 && !verified)
            fputs("Not connecting to the game server until the account is signed in\n", stderr);
        if (argc == 3 && verified) {
            PROCESS_INFORMATION client;
            STARTUPINFOW client_startup = { .cb = sizeof(client_startup) };
            if (CreateProcessW(pager, connect, NULL, NULL, FALSE, 0, NULL, NULL,
                               &client_startup, &client)) {
                CloseHandle(client.hThread);
                CloseHandle(client.hProcess);
                fputs("Connecting to the game server\n", stderr);
            } else {
                fputs("Could not start the game server connection\n", stderr);
            }
        }
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
