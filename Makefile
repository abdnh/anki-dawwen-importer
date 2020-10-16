files = $(filter-out $(wildcard *.png), $(wildcard *))

package:
	zip -r ./dawwen_importer.ankiaddon $(files)
