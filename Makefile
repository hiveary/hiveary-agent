PYTHON=`which python`
DESTDIR=/
BUILDIR=$(CURDIR)/debian/hiveary-agent
PROJECT=hiveary-agent
VERSION=1.0.1

builddeb:
	$(PYTHON) setup.py sdist $(COMPILE) --dist-dir=../
	dpkg-buildpackage -i -I -rfakeroot


