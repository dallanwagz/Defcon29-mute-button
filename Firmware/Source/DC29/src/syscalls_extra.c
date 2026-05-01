#include <sys/types.h>

int _read(int file, char *ptr, int len)
{
	(void)file; (void)ptr; (void)len;
	return 0;
}

int _write(int file, char *ptr, int len)
{
	(void)file; (void)ptr;
	return len;
}
