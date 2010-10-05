
/******************** 64-bit hiddengcref32 support ********************/

typedef unsigned int hiddengcref32_t;


void RPyPointerTooBig(void);

#ifndef PYPY_NOT_MAIN_FILE
void RPyPointerTooBig(void) {
  fprintf(stderr, "Fatal error: Pointer too big or misaligned.  "
                  "This can occur if your C\n"
                  "compiler puts static data after the first 32GB "
                  "of virtual address space.\n");
  abort();
}
#endif


#define OP_SHOW_FROM_ADR32(x, r)  r = (void*)(((unsigned long)(x)) << 3)

#define OP_HIDE_INTO_ADR32_CHECK(x, r)  \
   r = (hiddengcref32_t)(((unsigned long)(x)) >> 3); \
   if ((void*)(((unsigned long)(r)) << 3) != (x)) \
     RPyPointerTooBig()

#define OP_HIDE_INTO_ADR32(x, r)  \
   RPyAssert(!(((long)(x)) & 0x7FFFFFFF8), "Pointer too big or misaligned"); \
   r = (hiddengcref32_t)(((unsigned long)(x)) >> 3)