/* SPDX-License-Identifier: GPL-3.0-or-later */
#include "lifecycle.h"
bool hk_can_commit(bool paired,bool seen_on,bool seen_off,bool storage_failed)
{return paired && seen_on && seen_off && !storage_failed;}
bool hk_trial_expired(bool committed,uint32_t elapsed_ms)
{return !committed && elapsed_ms>=1200000U;}
