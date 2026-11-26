#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wchar.h>

enum { ACCOUNT = 100, PASSWORD, SAVE, AUTOMATIC, LOGIN };

static void control(HWND dialog, int id, const wchar_t *class, const wchar_t *title,
                    DWORD style, int y)
{
    if (!CreateWindowW(class, title, WS_CHILD | WS_VISIBLE | style, 10, y, 315, 25,
                       dialog, (HMENU)(INT_PTR)id, GetModuleHandleW(NULL), NULL))
        ExitProcess(3);
}

static INT_PTR CALLBACK dialog_proc(HWND dialog, UINT message, WPARAM wparam, LPARAM lparam)
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
        SetTimer(dialog, 1, 15000, NULL);
        return TRUE;
    case WM_TIMER:
        EndDialog(dialog, 4);
        return TRUE;
    case WM_COMMAND:
        if (LOWORD(wparam) == PASSWORD && HIWORD(wparam) == EN_CHANGE) {
            EnableWindow(GetDlgItem(dialog, LOGIN), GetWindowTextLengthW(GetDlgItem(dialog, PASSWORD)) > 0);
            return TRUE;
        }
        if (LOWORD(wparam) == LOGIN && HIWORD(wparam) == BN_CLICKED) {
            wchar_t account[64], password[64];
            GetDlgItemTextW(dialog, ACCOUNT, account, 64);
            GetDlgItemTextW(dialog, PASSWORD, password, 64);
            EndDialog(dialog, wcscmp(account, L"LGplayer02") == 0 &&
                      wcscmp(password, L"fixture $`\\'\"!") == 0 &&
                      IsDlgButtonChecked(dialog, SAVE) == BST_CHECKED &&
                      IsDlgButtonChecked(dialog, AUTOMATIC) == BST_CHECKED ? 0 : 5);
            return TRUE;
        }
    }
    return FALSE;
}

int main(void)
{
    const struct {
        DLGTEMPLATE header;
        WORD menu, class, title;
    } dialog = { { WS_POPUP | WS_CAPTION | WS_SYSMENU | WS_VISIBLE, 0, 0, 0, 0, 235, 120 }, 0, 0, 0 };
    return (int)DialogBoxIndirectParamW(GetModuleHandleW(NULL), &dialog.header, NULL,
                                       dialog_proc, 0);
}
