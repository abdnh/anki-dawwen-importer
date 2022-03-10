.PHONY: all zip clean format
ADDON_NAME := dawwen_importer

all: zip

zip: $(ADDON_NAME).ankiaddon

$(ADDON_NAME).ankiaddon: src/*
	rm -f $@
	rm -rf src/__pycache__
	( cd src/; zip -r ../$@ * )

format:
	python -m black src/

clean:
	rm -f *.pyc
	rm -f src/*.pyc
	rm -f src/__pycache__
	rm -f $(ADDON_NAME).ankiaddon
