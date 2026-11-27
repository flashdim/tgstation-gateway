#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wchar.h>

enum { ACCOUNT = 100, PASSWORD, SAVE, AUTOMATIC, LOGIN, PAGER_LINK = 200 };

static HWND link;
static int exit_code = 4;
static const wchar_t server[] = L"byond://fixture.test:1337";

static void control(HWND dialog, int id, const wchar_t *class, const wchar_t *title,
                    DWORD style, int y)
{
    if (!CreateWindowW(class, title, WS_CHILD | WS_VISIBLE | style, 10, y, 315, 25,
                       dialog, (HMENU)(INT_PTR)id, GetModuleHandleW(NULL), NULL))
        ExitProcess(3);
}

static INT_PTR CALLBACK login_proc(HWND dialog, UINT message, WPARAM wparam, LPARAM lparam)
{
    (void)lparam;
    switch (message) {
    case WM_INITDIALOG:
        SetWindowTextW(dialog, L"Login");
        control(dialog, ACCOUNT, L"ComboBox", L"", CBS_DROPDOWN, 10);
        control(dialog, PASSWORD, L"Edit", L"", ES_PASSWORD, 40);
        control(dialog, SAVE, L"Button", L"Save password", BS_AUTOCHECKBOX, 70);
        control(dialog, AUTOMATIC, L"Button", L"Automatically login when program starts",
                BS_AUTOCHECKBOX, 100);
        control(dialog, LOGIN, L"Button", L"Login", BS_OWNERDRAW | WS_DISABLED, 130);
        SetDlgItemTextW(dialog, ACCOUNT, L"Guest");
        EnableWindow(GetDlgItem(dialog, PASSWORD), FALSE);
        EnableWindow(GetDlgItem(dialog, SAVE), FALSE);
        return TRUE;
    case WM_COMMAND:
        if (LOWORD(wparam) == ACCOUNT && HIWORD(wparam) == CBN_EDITCHANGE) {
            wchar_t account[64];
            GetDlgItemTextW(dialog, ACCOUNT, account, 64);
            BOOL enabled = wcscmp(account, L"LGplayer02") == 0;
            EnableWindow(GetDlgItem(dialog, PASSWORD), enabled);
            EnableWindow(GetDlgItem(dialog, SAVE), enabled);
            return TRUE;
        }
        if (LOWORD(wparam) == PASSWORD && HIWORD(wparam) == EN_CHANGE) {
            EnableWindow(GetDlgItem(dialog, LOGIN),
                         GetWindowTextLengthW(GetDlgItem(dialog, PASSWORD)) > 0);
            return TRUE;
        }
        if (LOWORD(wparam) == LOGIN && HIWORD(wparam) == BN_CLICKED) {
            wchar_t account[64], password[64];
            GetDlgItemTextW(dialog, ACCOUNT, account, 64);
            GetDlgItemTextW(dialog, PASSWORD, password, 64);
            BOOL valid = wcscmp(account, L"LGplayer02") == 0 &&
                         wcscmp(password, L"fixture $`\\'\"!") == 0 &&
                         IsDlgButtonChecked(dialog, SAVE) == BST_CHECKED &&
                         IsDlgButtonChecked(dialog, AUTOMATIC) == BST_CHECKED;
            EndDialog(dialog, valid ? 0 : 5);
            return TRUE;
        }
    }
    return FALSE;
}

static INT_PTR CALLBACK pager_proc(HWND window, UINT message, WPARAM wparam, LPARAM lparam)
{
    (void)wparam;
    switch (message) {
    case WM_CREATE: {
        wchar_t signed_in[2];
        BOOL saved = GetEnvironmentVariableW(L"BYOND_LOGIN_TEST_SIGNED_IN", signed_in, 2) == 1 &&
                     signed_in[0] == L'1';
        link = CreateWindowW(L"Button", saved ? L"LGplayer02" : L"Logout",
                             WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON, 10, 10, 300, 30, window,
                             (HMENU)(INT_PTR)PAGER_LINK, GetModuleHandleW(NULL), NULL);
        if (!link)
            return -1;
        SetTimer(window, 1, 20000, NULL);
        return 0;
    }
    case WM_COMMAND:
        /* Only the native accelerator works; accessibility actions are no-ops. */
        if (LOWORD(wparam) != PAGER_LINK || HIWORD(wparam) != 1)
            return 0;
        if (GetWindowTextLengthW(link) == 10) {
            exit_code = 7;
            PostQuitMessage(exit_code);
            return 0;
        }
        if (GetWindowTextLengthW(link) == 6) {
            SetWindowTextW(link, L" log in ");
            return 0;
        }
        if (GetWindowTextLengthW(link) == 8) {
            const struct {
                DLGTEMPLATE header;
                WORD menu, class, title;
            } template = {
                { WS_POPUP | WS_CAPTION | WS_SYSMENU, 0, 0, 0, 0, 235, 160 }, 0, 0, 0
            };
            exit_code = (int)DialogBoxIndirectParamW(GetModuleHandleW(NULL),
                                                      &template.header, window, login_proc, 0);
            if (exit_code) {
                PostQuitMessage(exit_code);
                return 0;
            }
            /* Signed in; wait for the helper to open the server. */
            SetWindowTextW(link, L"LGplayer02");
            exit_code = 6;
        }
        return 0;
    case WM_APP:
        if (GetWindowTextLengthW(link) == 10) {
            exit_code = 0;
            PostQuitMessage(exit_code);
        }
        return 0;
    case WM_TIMER:
        PostQuitMessage(exit_code);
        return 0;
    case WM_DESTROY:
        PostQuitMessage(exit_code);
        return 0;
    }
    return DefWindowProcW(window, message, wparam, lparam);
}

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR command, int show)
{
    (void)previous;
    (void)show;
    if (*command) {
        HWND pager = FindWindowW(L"ByondLoginFixture", NULL);
        return wcscmp(command, server) == 0 && pager && PostMessageW(pager, WM_APP, 0, 0) ? 0 : 8;
    }
    WNDCLASSW cls = {0};
    cls.lpfnWndProc = pager_proc;
    cls.hInstance = instance;
    cls.lpszClassName = L"ByondLoginFixture";
    if (!RegisterClassW(&cls))
        return 2;
    HWND window = CreateWindowW(cls.lpszClassName, L"BYOND",
                                WS_OVERLAPPEDWINDOW | WS_VISIBLE,
                                CW_USEDEFAULT, CW_USEDEFAULT, 500, 300,
                                NULL, NULL, instance, NULL);
    if (!window)
        return 2;
    ShowWindow(window, SW_SHOW);
    ACCEL shortcut = { .fVirt = FVIRTKEY | FCONTROL, .key = 'L', .cmd = PAGER_LINK };
    HACCEL accelerators = CreateAcceleratorTableW(&shortcut, 1);
    if (!accelerators)
        return 2;
    MSG message;
    while (GetMessageW(&message, NULL, 0, 0) > 0) {
        if (!TranslateAcceleratorW(window, accelerators, &message)) {
            TranslateMessage(&message);
            DispatchMessageW(&message);
        }
    }
    DestroyAcceleratorTable(accelerators);
    return exit_code;
}
