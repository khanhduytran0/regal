/*********************************************************************
 *
 * Copyright 2012 Intel Corporation
 * All Rights Reserved.
 *
 * Permission is hereby granted, free of charge, to any person
 * obtaining a copy of this software and associated documentation
 * files (the "Software"), to deal in the Software without
 * restriction, including without limitation the rights to use, copy,
 * modify, merge, publish, distribute, sublicense, and/or sell copies
 * of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 * The above copyright notice and this permission notice shall be
 * included in all copies or substantial portions of the Software.
 *
 * THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
 * EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
 * MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
 * NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
 * BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
 * ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
 * CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
 * SOFTWARE.
 *
 *********************************************************************/

#include <assert.h>

// Default to multi-threading support using TLS,
// otherwise specify -DAPITRACE_TLS=0
//
// apitrace TLS support requires C++ TR1 (except Windows)
// and pthreads for Linux/Mac/Android

#ifndef APITRACE_TLS
# if defined(_MSC_VER) && _MSC_VER<1600
#  define APITRACE_TLS 0
# else
#  define APITRACE_TLS 1
# endif
#endif

// TLS headers

#if APITRACE_TLS
#include <map>
#if defined(_MSC_VER) || (defined(__MAC_OS_X_VERSION_MIN_REQUIRED) && __MAC_OS_X_VERSION_MIN_REQUIRED >= 1090)
#include <memory>
#else
#include <tr1/memory>
#include <memory>
#endif
#endif

#include <os_thread.hpp>
#include <glproc.hpp>
#include <gltrace.hpp>

// TODO - this is needed for Regal purposes only

namespace Regal { namespace Trace { 

extern void glViewport( GLint x, GLint y, GLsizei width, GLsizei height );
extern void glScissor( GLint x, GLint y, GLsizei width, GLsizei height );

} }

namespace gltrace {

#if APITRACE_TLS
#if defined(__MAC_OS_X_VERSION_MIN_REQUIRED) && __MAC_OS_X_VERSION_MIN_REQUIRED >= 1090
typedef std::shared_ptr<Context> context_ptr_t;
#else
typedef std::tr1::shared_ptr<Context> context_ptr_t;
#endif
static os::recursive_mutex context_map_mutex;
#else
typedef Context *context_ptr_t;
#endif

static std::map<uintptr_t, context_ptr_t> context_map;

class ThreadState {
public:
    context_ptr_t current_context;
    context_ptr_t dummy_context;     /*
                                      * For cases when there is no current
                                      * context, but the app still calls some
                                      * GL function that expects one.
                                      */
    ThreadState() : dummy_context(new Context)
    {
        current_context = dummy_context;
    }

#if !APITRACE_TLS
    ~ThreadState()
    {
      delete dummy_context;
      if (current_context!=dummy_context)
        delete current_context;
    }
#endif

};

#if APITRACE_TLS

#if _WIN32
static OS_THREAD_SPECIFIC_PTR(ThreadState) thread_state;

static ThreadState *get_ts(void)
{
    ThreadState *ts = thread_state;
    if (!ts) {
        thread_state = ts = new ThreadState;
    }

    return ts;
}
#else
#include <pthread.h>
pthread_key_t thread_state_key = 0;
static ThreadState *get_ts() {
    if( thread_state_key == 0 ) {
        pthread_key_create( &thread_state_key, NULL );
    }
    ThreadState *ts = static_cast<ThreadState *>( pthread_getspecific( thread_state_key ) );
    if( !ts ) {
        ts = new ThreadState;
        pthread_setspecific( thread_state_key, ts );
    }
    return ts;
}

#endif

#else
static ThreadState thread_state;
static ThreadState *get_ts() { return &thread_state; }
#endif

static void _retainContext(context_ptr_t ctx)
{
    ctx->retain_count++;
}

void retainContext(uintptr_t context_id)
{
#if APITRACE_TLS
    context_map_mutex.lock();
#endif
    if (context_map.find(context_id) != context_map.end())
        _retainContext(context_map[context_id]);
#if APITRACE_TLS
    context_map_mutex.unlock();
#endif
}

static bool _releaseContext(context_ptr_t ctx)
{
    return !(--ctx->retain_count);
}

/*
 * return true if the context was destroyed, false if only its refcount
 * got decreased. Note that even if the context was destroyed it may
 * still live, if it's the currently selected context (by setContext).
 */
bool releaseContext(uintptr_t context_id)
{
    bool res = false;

#if APITRACE_TLS
    context_map_mutex.lock();
#endif

    /*
     * This can potentially called (from glX) with an invalid context_id,
     * so don't assert on it being valid.
     */
    if (context_map.find(context_id) != context_map.end()) {
        res = _releaseContext(context_map[context_id]);
        if (res)
            context_map.erase(context_id);
    }
#if APITRACE_TLS
    context_map_mutex.unlock();
#endif

    return res;
}

void createContext(uintptr_t context_id)
{
    // wglCreateContextAttribsARB causes internal calls to wglCreateContext to be
    // traced, causing context to be defined twice.
    if (context_map.find(context_id) != context_map.end()) {
        return;
    }

    context_ptr_t ctx(new Context);

#if APITRACE_TLS
    context_map_mutex.lock();
#endif

    _retainContext(ctx);
    context_map[context_id] = ctx;

#if APITRACE_TLS
    context_map_mutex.unlock();
#endif
}

void setContext(uintptr_t context_id)
{
    ThreadState *ts = get_ts();
    context_ptr_t ctx;

#if APITRACE_TLS
    context_map_mutex.lock();
#endif

    assert(context_map.find(context_id) != context_map.end());
    ctx = context_map[context_id];

#if APITRACE_TLS
    context_map_mutex.unlock();
#endif

    ts->current_context = ctx;

    if (!ctx->bound) {
        /*
         * The default viewport and scissor state is set when a context is
         * first made current, with values matching the bound drawable.  Many
         * applications never thouch the default state ever again.
         *
         * Since we currently don't trace window sizes, and rely on viewport
         * calls to deduct, emit fake calls here so that viewport/scissor state
         * can be deducated.
         *
         * FIXME: don't call the real functions here -- just emit the fake
         * calls.
         */
        GLint viewport[4] = {0, 0, 0, 0};
        GLint scissor[4] = {0, 0, 0, 0};
        _glGetIntegerv(GL_VIEWPORT, viewport);
        _glGetIntegerv(GL_SCISSOR_BOX, scissor);

        /*
         * On MacOSX the current context and surface are set independently, and
         * we might be called before both are set, so ignore empty boxes.
         */
        if (viewport[2] && viewport[3] && scissor[2] && scissor[3]) {
            ::Regal::Trace::glViewport(viewport[0], viewport[1], viewport[2], viewport[3]);
            ::Regal::Trace::glScissor(scissor[0], scissor[1], scissor[2], scissor[3]);
            ctx->bound = true;
        }
    }
}

void clearContext(void)
{
    ThreadState *ts = get_ts();

    ts->current_context = ts->dummy_context;
}

Context *getContext(void)
{
#if APITRACE_TLS
    return get_ts()->current_context.get();
#else
    return get_ts()->current_context;
#endif
}

}
