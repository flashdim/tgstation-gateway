#define wmain byond_login_main
#include "../container/byond-login.c"
#undef wmain

static LONG test_role;
static unsigned actions;
static HRESULT action_result;

static HRESULT STDMETHODCALLTYPE node_name(IAccessible *node, VARIANT child, BSTR *name)
{
    (void)node;
    (void)child;
    *name = SysAllocString(L"Logout");
    return *name ? S_OK : E_OUTOFMEMORY;
}

static HRESULT STDMETHODCALLTYPE node_role(IAccessible *node, VARIANT child, VARIANT *role)
{
    (void)node;
    (void)child;
    role->vt = VT_I4;
    role->lVal = test_role;
    return S_OK;
}

static HRESULT STDMETHODCALLTYPE node_action(IAccessible *node, VARIANT child)
{
    (void)node;
    (void)child;
    ++actions;
    return action_result;
}

int main(void)
{
    IAccessibleVtbl methods = {
        .get_accName = node_name,
        .get_accRole = node_role,
        .accDoDefaultAction = node_action,
    };
    IAccessible node = { .lpVtbl = &methods };
    VARIANT self;
    VariantInit(&self);
    self.vt = VT_I4;
    self.lVal = CHILDID_SELF;
    struct link_search search = { .name = L"Logout" };
    action_result = S_OK;

    /* WebView exposes text and a link with identical names. Text's no-op can succeed. */
    test_role = ROLE_SYSTEM_STATICTEXT;
    activate_if_match(&node, self, &search);
    test_role = ROLE_SYSTEM_TEXT;
    activate_if_match(&node, self, &search);
    if (search.found || actions)
        return 1;

    test_role = ROLE_SYSTEM_LINK;
    activate_if_match(&node, self, &search);
    if (!search.found || search.result != S_OK || actions != 1)
        return 2;

    search.found = FALSE;
    action_result = S_FALSE;
    activate_if_match(&node, self, &search);
    if (!search.found || !FAILED(search.result) || actions != 2)
        return 3;
    return 0;
}
