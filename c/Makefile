CC ?= cc
CFLAGS ?= -O2 -Wall -Wextra -std=c11

ampp: ampp.c
	$(CC) $(CFLAGS) -o ampp ampp.c

run: ampp
	./ampp

clean:
	rm -f ampp

.PHONY: run clean
