#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wchar.h>

enum { ACCOUNT = 100, PASSWORD, SAVE, AUTOMATIC, LOGIN, PAGER_LINK = 200 };

static HWND link;
static int exit_code = 4;

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
    case WM_CREATE:
        link = CreateWindowW(L"Button", L"Logout", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
                             10, 10, 300, 30, window,
                             (HMENU)(INT_PTR)PAGER_LINK, GetModuleHandleW(NULL), NULL);
        if (!link)
            return -1;
        SetTimer(window, 1, 20000, NULL);
        return 0;
    case WM_COMMAND:
        if (LOWORD(wparam) != PAGER_LINK || HIWORD(wparam) != BN_CLICKED)
            return 0;
        if (GetWindowTextLengthW(link) == 6) {
            SetWindowTextW(link, L"Login");
            return 0;
        }
        if (GetWindowTextLengthW(link) == 5) {
            const struct {
                DLGTEMPLATE header;
                WORD menu, class, title;
            } template = {
                { WS_POPUP | WS_CAPTION | WS_SYSMENU, 0, 0, 0, 0, 235, 160 }, 0, 0, 0
            };
            exit_code = (int)DialogBoxIndirectParamW(GetModuleHandleW(NULL),
                                                      &template.header, window, login_proc, 0);
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
    (void)command;
    (void)show;
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
    MSG message;
    while (GetMessageW(&message, NULL, 0, 0) > 0) {
        TranslateMessage(&message);
        DispatchMessageW(&message);
    }
    return exit_code;
}
