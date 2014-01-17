PYTHON=`which python`
DESTDIR=/
BUILDIR=$(CURDIR)/debian/hiveary-agent
PROJECT=hiveary-agent
VERSION=1.2.0

builddeb:
	$(PYTHON) setup.py sdist $(COMPILE) --dist-dir=../
	dpkg-buildpackage -i -I -rfakeroot


